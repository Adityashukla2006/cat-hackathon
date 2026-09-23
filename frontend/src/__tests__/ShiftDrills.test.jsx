import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import ShiftDrills from '../components/ShiftDrills'
import { getJson, postJson } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

const DRILLS = [
  {
    id: 'seatbelt-2',
    kind: 'seatbelt',
    minute: 2,
    title: 'Seatbelt before start',
    lesson_id: 'seatbelt',
    practice: null,
    scenario: 'At 07:02 your engine was running with the seatbelt unbuckled.',
    question: "What's the right order?",
    options: ['Start, then buckle', 'Buckle, then start', 'Only before travel'],
  },
  {
    id: 'idle_deviation-159',
    kind: 'idle_deviation',
    minute: 159,
    title: 'Long idle wait',
    lesson_id: 'idle-fuel',
    practice: 'grade',
    scenario: 'At 09:39 you sat idling.',
    question: 'You are waiting. What do you do?',
    options: ['Keep revving', 'Idle down and tell dispatch', 'Leave'],
  },
]

describe('ShiftDrills', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getJson.mockResolvedValue(DRILLS)
  })

  it('lists the shift moments with their times', async () => {
    render(<ShiftDrills />)
    expect(await screen.findByText('07:02 · Seatbelt before start')).toBeInTheDocument()
    expect(screen.getByText('09:39 · Long idle wait')).toBeInTheDocument()
    expect(getJson).toHaveBeenCalledWith('/shifts/1/drills')
  })

  it('checks an answer and offers practice', async () => {
    postJson.mockResolvedValue({
      correct: false,
      correct_option: 'Idle down and tell dispatch',
      explanation: 'Let dispatch reshuffle the work.',
    })
    const onPractice = vi.fn()
    render(<ShiftDrills onPractice={onPractice} />)
    await userEvent.click(await screen.findByRole('button', { name: 'Keep revving' }))
    expect(postJson).toHaveBeenCalledWith('/shifts/1/drills/idle_deviation-159/answer', {
      operator_id: 1,
      answer: 0,
    })
    expect(await screen.findByText('Better: Idle down and tell dispatch')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Keep revving' })).toHaveClass('bg-alert-red')
    await userEvent.click(screen.getByRole('button', { name: 'Practice in the simulator' }))
    expect(onPractice).toHaveBeenCalledWith('grade')
  })

  it('handles an empty shift', async () => {
    getJson.mockResolvedValue([])
    render(<ShiftDrills />)
    expect(await screen.findByText(/Nothing to review/)).toBeInTheDocument()
  })
})
