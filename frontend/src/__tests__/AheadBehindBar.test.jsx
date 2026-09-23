import { render, screen } from '@testing-library/react'
import AheadBehindBar, { describeDelta } from '../components/AheadBehindBar'

describe('describeDelta', () => {
  it.each([
    [null, 'Waiting for shift', 'idle'],
    [1.2, 'On track', 'ok'],
    [-1.9, 'On track', 'ok'],
    [6.4, '6 min ahead', 'ahead'],
    [-4, '4 min behind', 'behind'],
    [-12, '12 min behind', 'late'],
  ])('%s -> %s', (delta, label, tone) => {
    expect(describeDelta(delta)).toEqual({ label, tone })
  })
})

describe('AheadBehindBar', () => {
  it('fills to the right when ahead', () => {
    render(<AheadBehindBar delta={15} />)
    expect(screen.getByText('15 min ahead')).toBeInTheDocument()
    const fill = screen.getByTestId('delta-fill')
    expect(fill.style.left).toBe('50%')
    expect(fill.style.width).toBe('25%')
  })

  it('fills to the left when behind and caps at the range', () => {
    render(<AheadBehindBar delta={-90} />)
    expect(screen.getByText('90 min behind')).toHaveAttribute('data-tone', 'late')
    const fill = screen.getByTestId('delta-fill')
    expect(fill.style.right).toBe('50%')
    expect(fill.style.width).toBe('50%')
  })
})
