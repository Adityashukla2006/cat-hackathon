import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import CoachCard from '../components/CoachCard'
import { getJson } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
}))

const ADVICE = {
  note: 'Start with the seatbelt lesson.',
  recommendations: [
    { lesson_id: 'seatbelt', title: 'Seatbelt and cab safety', weight: 3, reasons: ['engine ran with the seatbelt unbuckled'], practice: null },
    { lesson_id: 'soft-ground', title: 'Soft ground, slopes, and edges', weight: 3, reasons: ['reported: track sank'], practice: null },
  ],
  suggest_instructor: 'Seatbelt and cab safety',
}

describe('CoachCard', () => {
  beforeEach(() => vi.clearAllMocks())

  it('shows the note and opens a recommended lesson', async () => {
    getJson.mockResolvedValue(ADVICE)
    const onOpenLesson = vi.fn()
    render(<CoachCard onOpenLesson={onOpenLesson}>{(topic) => <p>Book for {topic}</p>}</CoachCard>)
    expect(await screen.findByText('Start with the seatbelt lesson.')).toBeInTheDocument()
    expect(getJson).toHaveBeenCalledWith('/operators/1/coach')
    expect(screen.getByText('Because: engine ran with the seatbelt unbuckled')).toBeInTheDocument()
    expect(screen.getByText('Book for Seatbelt and cab safety')).toBeInTheDocument()
    await userEvent.click(screen.getByRole('button', { name: /2\. Soft ground/ }))
    expect(onOpenLesson).toHaveBeenCalledWith('soft-ground')
  })

  it('renders nothing when the coach is unavailable', async () => {
    getJson.mockImplementation(() => Promise.reject(new Error('404')))
    const { container } = render(<CoachCard onOpenLesson={() => {}} />)
    await Promise.resolve()
    expect(container).toBeEmptyDOMElement()
  })
})
