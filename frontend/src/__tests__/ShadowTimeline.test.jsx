import { render, screen } from '@testing-library/react'
import ShadowTimeline from '../components/ShadowTimeline'
import { TIMELINE } from './fakeSocket'

describe('ShadowTimeline', () => {
  it('shows a loading state without a timeline', () => {
    render(<ShadowTimeline timeline={null} />)
    expect(screen.getByText(/Loading shadow/)).toBeInTheDocument()
  })

  it('sizes tasks by p50 and shows the total band', () => {
    render(<ShadowTimeline timeline={TIMELINE} minute={0} />)
    expect(screen.getByTestId('task-1').style.width).toBe('40%')
    expect(screen.getByTestId('task-2').style.width).toBe('60%')
    expect(screen.getByText('80–130 min')).toBeInTheDocument()
    expect(screen.getByTestId('task-2')).toHaveAttribute('title', 'Cut ditch: 50–80 min')
  })

  it('highlights the current task and places the now marker', () => {
    render(<ShadowTimeline timeline={TIMELINE} minute={50} currentSeq={2} />)
    expect(screen.getByTestId('task-2')).toHaveAttribute('aria-current', 'step')
    expect(screen.getByTestId('task-1')).not.toHaveAttribute('aria-current')
    expect(screen.getByTestId('now-marker').style.left).toBe('50%')
  })

  it('clamps the now marker at the end and lists risk points', () => {
    render(<ShadowTimeline timeline={TIMELINE} minute={500} />)
    expect(screen.getByTestId('now-marker').style.left).toBe('100%')
    expect(screen.getByText(/could run long/)).toBeInTheDocument()
  })
})
