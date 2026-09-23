import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Training from '../pages/Training'
import { getJson, postJson } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

let walkaroundProps
vi.mock('../components/Walkaround', () => ({
  default: (props) => {
    walkaroundProps = props
    return <p>Walkaround inspection</p>
  },
}))

const MODULES = [
  {
    id: 'safety-basics',
    title: 'Safety basics',
    lessons: [
      { id: 'seatbelt', title: 'Seatbelt and cab safety', guide_id: 'seatbelt-and-cab-safety', practice: null, best_score: 1, passed: true },
      { id: 'walkaround', title: 'Pre-start walkaround', guide_id: 'pre-start-walkaround', practice: 'walkaround', best_score: null, passed: false },
    ],
  },
]

const LESSON = {
  id: 'walkaround',
  title: 'Pre-start walkaround',
  guide_id: 'pre-start-walkaround',
  key_points: ['Walk the machine in one direction.'],
  practice: 'walkaround',
  questions: [
    { question: 'How do you check a hose?', options: ['Touch it', 'Look, never touch'] },
    { question: 'Damaged part?', options: ['Operate', 'Tag out'] },
  ],
}

const GUIDE = {
  id: 'pre-start-walkaround',
  title: 'Pre-start walkaround inspection',
  sections: [{ heading: 'Before you walk', text: 'Park on **level** ground.' }],
}

describe('Training page', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    getJson.mockImplementation(async (path) => {
      if (path.startsWith('/training/modules')) return MODULES
      if (path === '/training/lessons/walkaround') return LESSON
      if (path === '/guides/pre-start-walkaround') return GUIDE
      throw new Error(`unexpected ${path}`)
    })
  })

  it('lists modules with progress', async () => {
    render(<Training />)
    expect(await screen.findByText('Safety basics')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Seatbelt and cab safety/ })).toHaveTextContent('✓ Passed 100%')
    expect(screen.getByRole('button', { name: /Pre-start walkaround/ })).toHaveTextContent('Not started')
    expect(getJson).toHaveBeenCalledWith(expect.stringContaining('/training/modules?operator_id=1'))
  })

  it('opens a lesson, shows the guide, and grades the quiz', async () => {
    postJson.mockResolvedValue({
      lesson_id: 'walkaround',
      score: 0.5,
      passed: false,
      correct: [true, false],
      explanations: ['Look, never touch.', 'Tag it out.'],
    })
    render(<Training />)
    await userEvent.click(await screen.findByRole('button', { name: /Pre-start walkaround/ }))
    expect(await screen.findByText('✔ Walk the machine in one direction.')).toBeInTheDocument()

    await userEvent.click(screen.getByRole('button', { name: 'Read the guide' }))
    expect(await screen.findByText('Park on level ground.')).toBeInTheDocument()

    const check = screen.getByRole('button', { name: 'Check answers' })
    expect(check).toBeDisabled()
    await userEvent.click(screen.getByRole('button', { name: 'Look, never touch' }))
    await userEvent.click(screen.getByRole('button', { name: 'Operate' }))
    await userEvent.click(check)

    expect(postJson).toHaveBeenCalledWith('/training/lessons/walkaround/quiz', {
      operator_id: 1,
      answers: [1, 0],
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Not yet: 50%')
    expect(screen.getByRole('button', { name: 'Look, never touch' })).toHaveClass('bg-emerald-500')
    expect(screen.getByRole('button', { name: 'Operate' })).toHaveClass('bg-alert-red')
    expect(screen.getByText('Tag it out.')).toBeInTheDocument()
  })

  it('jumps from a lesson to its practice and records the result', async () => {
    postJson.mockResolvedValue({})
    render(<Training />)
    await userEvent.click(await screen.findByRole('button', { name: /Pre-start walkaround/ }))
    await userEvent.click(await screen.findByRole('button', { name: 'Practice this' }))
    expect(screen.getByRole('tab', { name: 'Walkaround' })).toHaveAttribute('aria-selected', 'true')
    walkaroundProps.onComplete({ score: 90 })
    await waitFor(() =>
      expect(postJson).toHaveBeenCalledWith('/training/results', {
        operator_id: 1,
        activity_id: 'walkaround:leak',
        score: 0.9,
      }),
    )
  })
})
