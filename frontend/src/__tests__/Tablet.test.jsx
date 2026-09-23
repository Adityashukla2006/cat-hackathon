import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Tablet, { clock } from '../pages/Tablet'
import { getJson } from '../lib/api'
import { TIMELINE, frame, makeFakeSocket } from './fakeSocket'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
}))

describe('clock', () => {
  it('formats shift minutes from 07:00', () => {
    expect(clock(0)).toBe('07:00')
    expect(clock(135)).toBe('09:15')
  })
})

describe('Tablet page', () => {
  beforeEach(() => {
    getJson.mockResolvedValue(TIMELINE)
  })

  it('loads the shadow and connects to the replay socket', async () => {
    const { socket, createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} />)
    expect(await screen.findByTestId('task-1')).toBeInTheDocument()
    expect(getJson).toHaveBeenCalledWith('/demo/shadow')
    expect(socket.url).toMatch(/^ws.*\/ws\/telemetry\?speed=60$/)
  })

  it('shows live telemetry, the delta, and warns on an unbuckled seatbelt', async () => {
    const { socket, createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} />)
    await screen.findByTestId('task-1')
    socket.open()
    socket.emit({ type: 'telemetry', frame: frame({ minute: 3, seatbelt: false, task_seq: null }) })
    socket.emit({ type: 'telemetry', frame: frame({ machine_id: 2, minute: 3, load_pct: 99 }) })
    expect(screen.getByLabelText('Shift clock')).toHaveTextContent('07:03')
    expect(screen.getByText('Unbuckled').parentElement).toHaveClass('bg-alert-red')
    expect(screen.queryByText('99%')).not.toBeInTheDocument()

    socket.emit({ type: 'telemetry', frame: frame({ minute: 50, task_seq: 2 }) })
    socket.emit({ type: 'shadow_delta', minute: 50, delta_min: -7 })
    expect(screen.getByText('7 min behind')).toBeInTheDocument()
    expect(screen.getByTestId('task-2')).toHaveAttribute('aria-current', 'step')
  })

  it('sends pause and resume controls', async () => {
    const { socket, createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} />)
    socket.open()
    await userEvent.click(screen.getByRole('button', { name: 'Pause' }))
    await userEvent.click(screen.getByRole('button', { name: 'Resume' }))
    expect(socket.sent).toEqual([{ action: 'pause' }, { action: 'resume' }])
  })

  it('shows an error when the shadow cannot load', async () => {
    getJson.mockImplementation(() => Promise.reject(new Error('503 /demo/shadow')))
    const { createSocket } = makeFakeSocket()
    render(<Tablet createSocket={createSocket} />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Shadow unavailable')
  })
})
