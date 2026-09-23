import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import AlertBanner from '../components/AlertBanner'
import BriefingCard from '../components/BriefingCard'
import ReplanCard from '../components/ReplanCard'
import { TIMELINE } from './fakeSocket'

const alert = (overrides) => ({
  id: 1,
  shift_id: 1,
  minute: 2,
  kind: 'seatbelt',
  severity: 'critical',
  message: 'Seatbelt unbuckled with the engine on.',
  acknowledged: false,
  created_at: '2026-09-23T07:02:00Z',
  ...overrides,
})

describe('AlertBanner', () => {
  it('renders nothing without open alerts', () => {
    const { container } = render(
      <AlertBanner alerts={[alert({ acknowledged: true })]} onAcknowledge={() => {}} />,
    )
    expect(container).toBeEmptyDOMElement()
  })

  it('shows the most severe open alert first with a count of the rest', () => {
    render(
      <AlertBanner
        alerts={[
          alert({ id: 2, minute: 159, kind: 'idle_deviation', severity: 'warning', message: 'Idle' }),
          alert(),
        ]}
        onAcknowledge={() => {}}
      />,
    )
    expect(screen.getByRole('alert')).toHaveAttribute('data-severity', 'critical')
    expect(screen.getByText('Buckle up')).toBeInTheDocument()
    expect(screen.getByText('+1 more')).toBeInTheDocument()
  })

  it('acknowledges with one big button', async () => {
    const onAcknowledge = vi.fn()
    render(<AlertBanner alerts={[alert()]} onAcknowledge={onAcknowledge} />)
    await userEvent.click(screen.getByRole('button', { name: 'Got it' }))
    expect(onAcknowledge).toHaveBeenCalledWith(expect.objectContaining({ id: 1 }))
  })
})

describe('ReplanCard', () => {
  const replan = { new_order: [1, 2], explanation: 'Trench first while fresh.' }

  it('lists only the upcoming tasks and dismisses', async () => {
    const onDismiss = vi.fn()
    render(
      <ReplanCard replan={replan} tasks={TIMELINE.tasks} currentSeq={1} onDismiss={onDismiss} />,
    )
    expect(screen.getByText('Trench first while fresh.')).toBeInTheDocument()
    expect(screen.getByText('1. Cut ditch')).toBeInTheDocument()
    expect(screen.queryByText(/Dig pit face A/)).not.toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: 'OK' }))
    expect(onDismiss).toHaveBeenCalled()
  })

  it('renders nothing without a replan', () => {
    const { container } = render(<ReplanCard replan={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('BriefingCard', () => {
  it('shows the briefing and collapses to the headline', async () => {
    const briefing = { headline: 'Ramp ditch is riskiest', key_risks: ['Wet ground'], focus_tip: 'Go slow.' }
    render(<BriefingCard briefing={briefing} />)
    expect(screen.getByText('Go slow.')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /Ramp ditch is riskiest/ }))
    expect(screen.queryByText('Go slow.')).not.toBeInTheDocument()
  })
})
