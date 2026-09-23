import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Supervisor from '../pages/Supervisor'
import { getJson, postJson } from '../lib/api'
import { frame, makeFakeSocket } from './fakeSocket'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

const PIN = {
  id: 3,
  kind: 'soft_ground',
  description: 'Right track sank at the ramp edge.',
  lat: 40.696,
  lon: -89.588,
  radius_m: 30,
  confidence: 1,
  active: true,
  last_confirmed_at: '2026-09-23T10:20:00Z',
  reported_by_machine_id: 1,
}
const ALERT = (id, minute, message, severity = 'warning') => ({
  id,
  shift_id: 1,
  minute,
  kind: 'idle_deviation',
  severity,
  message,
  acknowledged: false,
  created_at: '2026-09-23T07:00:00Z',
})

async function setup(snapshot = {}) {
  getJson.mockImplementation(async (path) => {
    if (path === '/shifts/1/alerts') return snapshot.alerts ?? []
    if (path === '/shifts/1/incidents') return snapshot.incidents ?? []
    if (path === '/hazards') return snapshot.pins ?? []
    throw new Error(path)
  })
  const { socket, createSocket } = makeFakeSocket()
  render(<Supervisor createSocket={createSocket} />)
  await waitFor(() => expect(getJson).toHaveBeenCalledWith('/hazards'))
  socket.open()
  return socket
}

describe('Supervisor console', () => {
  beforeEach(() => vi.clearAllMocks())

  it('loads the shift so far and shows both machines live', async () => {
    const socket = await setup({ alerts: [ALERT(1, 2, 'Seatbelt unbuckled', 'critical')], pins: [PIN] })
    expect(await screen.findByText('Seatbelt unbuckled')).toBeInTheDocument()
    expect(screen.getByText('Alerts (1 open)')).toBeInTheDocument()
    socket.emit({ type: 'telemetry', frame: frame({ minute: 160, task_seq: 3, idle: true }) })
    socket.emit({ type: 'telemetry', frame: frame({ machine_id: 2, minute: 160, speed_kph: 14 }) })
    socket.emit({ type: 'shadow_delta', minute: 160, delta_min: -9 })
    socket.emit({ type: 'fatigue', minute: 160, score: 0.36, factors: {} })
    expect(screen.getByLabelText('Site clock')).toHaveTextContent('09:40')
    expect(screen.getByTestId('operator-status')).toHaveTextContent('Task 3 · 9 min behind · fatigue 36%')
    expect(screen.getByLabelText('WL-02 status')).toHaveTextContent('Working · 14 km/h')
    expect(screen.getAllByTestId('machine-marker')).toHaveLength(2)
  })

  it('adds live alerts, incidents, replans, and hazard warnings', async () => {
    const socket = await setup()
    socket.emit({ type: 'alert', alert: ALERT(9, 159, 'Idle 10 min straight on task 3.') })
    socket.emit({ type: 'replan', minute: 159, replan: { new_order: [1, 2, 3, 6, 5, 4], explanation: 'Stockpile first.' } })
    socket.emit({
      type: 'incident_logged',
      incident: { id: 1, minute: 200, report: { category: 'ground', severity: 'warning', summary: 'Track sank.' } },
    })
    socket.emit({ type: 'hazard_pin', pin: PIN, created: true })
    socket.emit({ type: 'hazard_warning', machine_id: 2, pin: PIN, distance_m: 67 })
    expect(screen.getByText('Idle 10 min straight on task 3.')).toBeInTheDocument()
    expect(screen.getByText('Stockpile first.')).toBeInTheDocument()
    expect(screen.getByText('Track sank.')).toBeInTheDocument()
    expect(screen.getByText('Soft ground · 100% confidence')).toBeInTheDocument()
    expect(screen.getByText('WL-02 warned 67 m from Soft ground')).toBeInTheDocument()
  })

  it('reconfirms and clears hazards', async () => {
    await setup({ pins: [PIN] })
    postJson.mockResolvedValueOnce({ ...PIN, confidence: 1 }).mockResolvedValueOnce({ ...PIN, active: false })
    await userEvent.click(await screen.findByRole('button', { name: 'Reconfirm' }))
    expect(postJson).toHaveBeenCalledWith('/hazards/3/confirm', {})
    await userEvent.click(screen.getByRole('button', { name: 'Clear' }))
    expect(postJson).toHaveBeenCalledWith('/hazards/3/clear', {})
    expect(await screen.findByText('No active hazards.')).toBeInTheDocument()
  })

  it('pauses the shared replay', async () => {
    const socket = await setup()
    await userEvent.click(screen.getByRole('button', { name: 'Pause replay' }))
    expect(socket.sent).toEqual([{ action: 'pause' }])
    expect(screen.getByRole('button', { name: 'Resume replay' })).toBeInTheDocument()
  })
})
