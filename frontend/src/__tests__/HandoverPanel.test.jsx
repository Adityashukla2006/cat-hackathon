import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import HandoverPanel from '../components/HandoverPanel'
import { getJson } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
}))

const HANDOVER = {
  shift_id: 1,
  headline: '5 tasks completed, 30 minutes behind plan, 1 incident reported.',
  done: ['a', 'b', 'c', 'd', 'e'],
  carry_over: ['Load haul trucks at the pit (in progress)'],
  watch_outs: ['Soft ground at the haul ramp edge.'],
  hazards: [],
  incidents: ['Track sank.'],
  open_alerts: ['x', 'y'],
  minutes_vs_shadow: -30,
  source: 'llm',
}

describe('HandoverPanel', () => {
  beforeEach(() => vi.clearAllMocks())

  it('prepares the handover on demand', async () => {
    getJson.mockResolvedValue(HANDOVER)
    render(<HandoverPanel shiftId={1} />)
    await userEvent.click(screen.getByRole('button', { name: 'Prepare handover' }))
    expect(getJson).toHaveBeenCalledWith('/shifts/1/handover')
    expect(await screen.findByText(HANDOVER.headline)).toBeInTheDocument()
    expect(screen.getByText('Load haul trucks at the pit (in progress)')).toBeInTheDocument()
    expect(screen.getByText('Soft ground at the haul ramp edge.')).toBeInTheDocument()
    expect(screen.getByText(/Done: 5 tasks · incidents: 1 · open alerts: 2/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Refresh' })).toBeInTheDocument()
  })

  it('shows an error when the shift is unknown', async () => {
    getJson.mockImplementation(() => Promise.reject(new Error('404 /shifts/1/handover')))
    render(<HandoverPanel />)
    await userEvent.click(screen.getByRole('button', { name: 'Prepare handover' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Handover unavailable')
  })
})
