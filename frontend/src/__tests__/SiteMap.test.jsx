import { render, screen } from '@testing-library/react'
import SiteMap from '../components/SiteMap'
import { mergePin, warningToAlert } from '../lib/site'
import { frame } from './fakeSocket'

const PIN = {
  id: 3,
  kind: 'soft_ground',
  description: 'Right track sank at the ramp edge.',
  lat: 40.696,
  lon: -89.588,
  radius_m: 30,
  confidence: 0.5,
  active: true,
  last_confirmed_at: '2026-09-23T10:20:00Z',
  reported_by_machine_id: 1,
}

describe('site helpers', () => {
  it('merges pins by id and drops inactive ones', () => {
    const pins = mergePin([PIN], { ...PIN, confidence: 1 })
    expect(pins).toHaveLength(1)
    expect(pins[0].confidence).toBe(1)
    expect(mergePin(pins, { ...PIN, active: false })).toEqual([])
    expect(mergePin(pins, { ...PIN, id: 4 })).toHaveLength(2)
  })

  it('turns a hazard warning into a local banner alert', () => {
    const alert = warningToAlert({ machine_id: 2, pin: PIN, distance_m: 66.6 }, 258)
    expect(alert).toMatchObject({ local: true, kind: 'hazard_proximity', severity: 'warning' })
    expect(alert.message).toMatch(/^Soft ground 67 m ahead/)
  })
})

describe('SiteMap', () => {
  it('shows both machines and hazard circles scaled by confidence', () => {
    render(
      <SiteMap
        machines={{ 1: frame(), 2: frame({ machine_id: 2, lat: 40.694 }) }}
        pins={[PIN]}
        focusMachineId={2}
      />,
    )
    const markers = screen.getAllByTestId('machine-marker')
    expect(markers).toHaveLength(2)
    expect(screen.getByText('EX-01')).toBeInTheDocument()
    expect(screen.getByText('WL-02')).toBeInTheDocument()
    expect(markers[1]).toHaveAttribute('data-radius', '12')
    const circle = screen.getByTestId('hazard-circle')
    expect(circle).toHaveAttribute('data-radius', '30')
    expect(circle).toHaveAttribute('data-fill-opacity', String(0.15 + 0.35 * 0.5))
    expect(screen.getByText('Soft ground · 50%')).toBeInTheDocument()
  })
})
