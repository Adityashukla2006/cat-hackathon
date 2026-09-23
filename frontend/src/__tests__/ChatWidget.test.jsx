import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ChatWidget from '../components/ChatWidget'
import { postForm, postJson } from '../lib/api'
import { EDGE_MARGIN, STORAGE_KEY, loadPosition, snapToEdge } from '../lib/chatWidget'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  postJson: vi.fn(),
  postForm: vi.fn(),
}))

const VIEWPORT = { width: 1024, height: 768 } // jsdom's default window size
const BUBBLE = { width: 88, height: 88 }

function memoryStorage(initial = {}) {
  const data = { ...initial }
  return {
    getItem: (k) => (k in data ? data[k] : null),
    setItem: (k, v) => {
      data[k] = v
    },
    data,
  }
}

function drag(el, from, to) {
  fireEvent.pointerDown(el, { clientX: from.x, clientY: from.y, pointerId: 1 })
  fireEvent.pointerMove(el, { clientX: to.x, clientY: to.y, pointerId: 1 })
  fireEvent.pointerUp(el, { clientX: to.x, clientY: to.y, pointerId: 1 })
}

const tap = (el) => drag(el, { x: 5, y: 5 }, { x: 6, y: 6 })

describe('snapToEdge', () => {
  it('snaps to the nearer side and clamps vertically', () => {
    expect(snapToEdge({ x: 100, y: 300 }, BUBBLE, VIEWPORT)).toEqual({ x: EDGE_MARGIN, y: 300 })
    expect(snapToEdge({ x: 700, y: -50 }, BUBBLE, VIEWPORT)).toEqual({
      x: 1024 - 88 - EDGE_MARGIN,
      y: EDGE_MARGIN,
    })
    expect(snapToEdge({ x: 10, y: 5000 }, BUBBLE, VIEWPORT).y).toBe(768 - 88 - EDGE_MARGIN)
  })

  it('falls back when saved data is missing or broken', () => {
    const fallback = { x: 1, y: 2 }
    expect(loadPosition(memoryStorage(), fallback)).toBe(fallback)
    expect(loadPosition(memoryStorage({ [STORAGE_KEY]: '{bad' }), fallback)).toBe(fallback)
    expect(loadPosition(null, fallback)).toBe(fallback)
  })
})

describe('ChatWidget', () => {
  beforeEach(() => vi.clearAllMocks())

  it('starts as a bubble at the bottom-right edge', () => {
    render(<ChatWidget storage={memoryStorage()} />)
    const bubble = screen.getByTestId('chat-bubble')
    expect(bubble.style.left).toBe(`${1024 - 88 - EDGE_MARGIN}px`)
    expect(bubble.style.top).toBe(`${768 - 88 - EDGE_MARGIN}px`)
  })

  it('drags, snaps to the nearest edge, and remembers the position', () => {
    const storage = memoryStorage()
    render(<ChatWidget storage={storage} />)
    const bubble = screen.getByTestId('chat-bubble')
    drag(bubble, { x: 900, y: 700 }, { x: 200, y: 300 })
    const saved = JSON.parse(storage.data[STORAGE_KEY])
    expect(saved.x).toBe(EDGE_MARGIN) // dragged to the left half, snapped to the left edge
    expect(bubble.style.left).toBe(`${EDGE_MARGIN}px`)
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument() // a drag isn't a tap
  })

  it('restores a saved position', () => {
    const storage = memoryStorage({ [STORAGE_KEY]: JSON.stringify({ x: 12, y: 200 }) })
    render(<ChatWidget storage={storage} />)
    expect(screen.getByTestId('chat-bubble').style.top).toBe('200px')
  })

  it('opens on tap, answers a typed question, and shows sources', async () => {
    postJson.mockResolvedValue({
      answer: 'Keep it fastened.',
      sources: ['Seatbelt and cab safety > Keep it on'],
      escalate_to_supervisor: false,
    })
    render(<ChatWidget storage={memoryStorage()} />)
    tap(screen.getByTestId('chat-bubble'))
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'Can I unbuckle?')
    await userEvent.click(screen.getByRole('button', { name: 'Ask' }))
    expect(postJson).toHaveBeenCalledWith('/chat', { message: 'Can I unbuckle?' })
    expect(await screen.findByText('Keep it fastened.')).toBeInTheDocument()
    expect(screen.getByText(/From: Seatbelt and cab safety/)).toBeInTheDocument()
  })

  it('highlights an escalation', async () => {
    postJson.mockResolvedValue({ answer: 'Stop and call your supervisor.', sources: [], escalate_to_supervisor: true })
    render(<ChatWidget storage={memoryStorage()} />)
    tap(screen.getByTestId('chat-bubble'))
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'Max lift?{enter}')
    expect((await screen.findByText('Stop and call your supervisor.')).className).toMatch(
      /bg-alert-red/,
    )
  })

  it('minimizes when a safety alert fires and stays down while it is active', () => {
    const storage = memoryStorage()
    const { rerender } = render(<ChatWidget storage={storage} />)
    tap(screen.getByTestId('chat-bubble'))
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument()
    rerender(<ChatWidget storage={storage} alertActive />)
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument()
    tap(screen.getByTestId('chat-bubble'))
    expect(screen.queryByTestId('chat-panel')).not.toBeInTheDocument()
    rerender(<ChatWidget storage={storage} alertActive={false} />)
    tap(screen.getByTestId('chat-bubble'))
    expect(screen.getByTestId('chat-panel')).toBeInTheDocument()
  })

  it('goes voice-only while the machine is working and speaks the answer', async () => {
    postForm.mockResolvedValue({ transcript: 'how far behind am I' })
    postJson.mockResolvedValue({ answer: '12 min behind.', sources: [], escalate_to_supervisor: false })
    const speakAnswers = vi.fn()
    render(
      <ChatWidget
        storage={memoryStorage()}
        machineWorking
        speakAnswers={speakAnswers}
        startRecording={async () => ({ stop: async () => new Blob(['a']) })}
      />,
    )
    tap(screen.getByTestId('chat-bubble'))
    expect(screen.queryByLabelText('Ask the assistant')).not.toBeInTheDocument()
    expect(screen.getByText(/voice only/)).toBeInTheDocument()
    const talk = screen.getByRole('button', { name: /Hold to ask/ })
    fireEvent.pointerDown(talk)
    await waitFor(() => expect(talk).toHaveAttribute('data-state', 'recording'))
    fireEvent.pointerUp(talk)
    expect(await screen.findByText('12 min behind.')).toBeInTheDocument()
    expect(postJson).toHaveBeenCalledWith('/chat', { message: 'how far behind am I' })
    expect(speakAnswers).toHaveBeenCalledWith('12 min behind.')
  })

  it('tells the operator to call the supervisor when the assistant is down', async () => {
    postJson.mockImplementation(() => Promise.reject(new Error('502')))
    render(<ChatWidget storage={memoryStorage()} />)
    tap(screen.getByTestId('chat-bubble'))
    await userEvent.type(screen.getByLabelText('Ask the assistant'), 'hi{enter}')
    expect(await screen.findByText(/call your supervisor/)).toBeInTheDocument()
  })
})
