import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Tablet, { clock, reorderTimeline } from '../pages/Tablet'
import { getJson, postForm, postJson } from '../lib/api'
import { TIMELINE, frame, makeFakeSocket } from './fakeSocket'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
  postJson: vi.fn(),
  postForm: vi.fn(),
}))

const PLAN = {
  timeline: TIMELINE,
  risks: [],
  briefing: { headline: 'Trench is riskiest', key_risks: ['Wet ground'], focus_tip: 'Go slow.' },
  briefing_source: 'llm',
}

const ALERT = {
  id: 7,
  shift_id: 1,
  minute: 2,
  kind: 'seatbelt',
  severity: 'critical',
  message: 'Seatbelt unbuckled with the engine on.',
  acknowledged: false,
  created_at: '2026-09-23T07:02:00Z',
}

const fakeRecorder = async () => ({ stop: async () => new Blob(['a']) })

describe('helpers', () => {
  it('formats shift minutes from 07:00', () => {
    expect(clock(0)).toBe('07:00')
    expect(clock(135)).toBe('09:15')
  })

  it('reorders the timeline and recomputes start times', () => {
    const reordered = reorderTimeline(TIMELINE, [2, 1])
    expect(reordered.tasks.map((t) => [t.seq, t.start_min])).toEqual([
      [2, 0],
      [1, 60],
    ])
    expect(reorderTimeline(TIMELINE, null)).toBe(TIMELINE)
  })
})

describe('Tablet page', () => {
  beforeEach(() => {
    getJson.mockResolvedValue(PLAN)
    postJson.mockResolvedValue({})
  })

  async function setup() {
    const { socket, createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} startRecording={fakeRecorder} />)
    await screen.findByTestId('task-1')
    socket.open()
    return socket
  }

  it('loads the plan, shows the briefing, and connects to the replay socket', async () => {
    const socket = await setup()
    expect(getJson).toHaveBeenCalledWith('/demo/plan')
    expect(screen.getByText('Trench is riskiest')).toBeInTheDocument()
    expect(socket.url).toMatch(/^ws.*\/ws\/telemetry\?speed=60$/)
  })

  it('shows live telemetry, the delta, and fatigue', async () => {
    const socket = await setup()
    socket.emit({ type: 'telemetry', frame: frame({ minute: 50, task_seq: 2 }) })
    socket.emit({ type: 'shadow_delta', minute: 50, delta_min: -7 })
    socket.emit({ type: 'fatigue', minute: 50, score: 0.72, factors: {} })
    expect(screen.getByLabelText('Shift clock')).toHaveTextContent('07:50')
    expect(screen.getByText('7 min behind')).toBeInTheDocument()
    expect(screen.getByTestId('task-2')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByText('72%').parentElement).toHaveClass('bg-alert-red')
    expect(screen.queryByText('Trench is riskiest')).not.toBeInTheDocument()
  })

  it('warns on an unbuckled seatbelt tile', async () => {
    const socket = await setup()
    socket.emit({ type: 'telemetry', frame: frame({ minute: 3, seatbelt: false, task_seq: null }) })
    expect(screen.getByText('Unbuckled').parentElement).toHaveClass('bg-alert-red')
  })

  it('raises an alert banner and acknowledges it', async () => {
    const socket = await setup()
    socket.emit({ type: 'alert', alert: ALERT })
    expect(screen.getByText('Buckle up')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(screen.queryByText('Buckle up')).not.toBeInTheDocument()
    expect(postJson).toHaveBeenCalledWith('/alerts/7/ack', {})
  })

  it('shows a replan and reorders the timeline', async () => {
    const socket = await setup()
    socket.emit({
      type: 'replan',
      minute: 10,
      replan: { new_order: [2, 1], explanation: 'Trench first.' },
    })
    expect(screen.getByText('Trench first.')).toBeInTheDocument()
    const segments = screen.getAllByTestId(/^task-/).map((el) => el.dataset.testid)
    expect(segments).toEqual(['task-2', 'task-1'])
  })

  it('sends a voice note transcript over the socket and shows the logged report', async () => {
    postForm.mockResolvedValue({ transcript: 'soft ground at the ramp' })
    const socket = await setup()
    const button = screen.getByRole('button', { name: /Hold to report/ })
    fireEvent.pointerDown(button)
    await waitFor(() => expect(button).toHaveAttribute('data-state', 'recording'))
    fireEvent.pointerUp(button)
    await waitFor(() =>
      expect(socket.sent).toContainEqual({
        action: 'voice_note',
        transcript: 'soft ground at the ramp',
      }),
    )
    socket.emit({
      type: 'incident_logged',
      incident: { id: 1, report: { summary: 'Soft ground at the ramp edge.' } },
    })
    expect(screen.getByRole('status')).toHaveTextContent(
      'Report logged: Soft ground at the ramp edge.',
    )
  })

  it('sends pause and resume controls', async () => {
    const socket = await setup()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    await userEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(socket.sent).toEqual([{ action: 'pause' }, { action: 'resume' }])
  })

  it('shows an error when the plan cannot load', async () => {
    getJson.mockImplementation(() => Promise.reject(new Error('503 /demo/plan')))
    const { createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} />)
    expect(await screen.findByText(/Shadow unavailable/)).toBeInTheDocument()
  })
})
