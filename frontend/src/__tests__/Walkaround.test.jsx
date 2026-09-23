import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import Walkaround from '../components/Walkaround'
import {
  CHECKPOINTS,
  SCENARIOS,
  createInspection,
  inspect,
  observe,
  summarize,
} from '../lib/walkaround'

const ids = CHECKPOINTS.map((p) => p.id)

function inspectAll(scenarioId, verdictFor, order = ids) {
  return order.reduce((acc, id) => inspect(acc, id, verdictFor(id)), createInspection(scenarioId))
}

describe('walkaround logic', () => {
  it('shows the seeded defect or the normal view', () => {
    const inspection = createInspection('leak')
    expect(observe(inspection, 'hydraulics')).toMatch(/oil streak/)
    expect(observe(inspection, 'bucket')).toBe(CHECKPOINTS.find((p) => p.id === 'bucket').normal)
  })

  it('passes when every defect is flagged, in clockwise order', () => {
    const defects = SCENARIOS.leak.defects
    const result = summarize(inspectAll('leak', (id) => (defects[id] ? 'defect' : 'ok')))
    expect(result).toMatchObject({ complete: true, ordered: true, passed: true, score: 100 })
    expect(result.found.sort()).toEqual(['ground', 'hydraulics'])
    expect(result.safeToOperate).toBe(false)
  })

  it('accepts any starting point as long as the direction holds', () => {
    const rotated = [...ids.slice(3), ...ids.slice(0, 3)]
    expect(summarize(inspectAll('cab', () => 'ok', rotated)).ordered).toBe(true)
    const shuffled = [ids[1], ids[0], ...ids.slice(2)]
    expect(summarize(inspectAll('cab', () => 'ok', shuffled)).ordered).toBe(false)
  })

  it('fails on a missed defect and penalises false alarms', () => {
    const result = summarize(inspectAll('track', (id) => (id === 'bucket' ? 'defect' : 'ok')))
    expect(result.passed).toBe(false)
    expect(result.missed).toEqual(['right_track'])
    expect(result.falseAlarms).toEqual(['bucket'])
    expect(result.score).toBe(40 + 10 - 5)
  })

  it('re-inspecting replaces the verdict without changing the order', () => {
    let inspection = inspect(createInspection('track'), 'ground', 'defect')
    inspection = inspect(inspection, 'ground', 'ok')
    expect(inspection.verdicts.ground).toBe('ok')
    expect(inspection.order).toEqual(['ground'])
    expect(() => inspect(inspection, 'nope', 'ok')).toThrow()
    expect(() => inspect(inspection, 'ground', 'maybe')).toThrow()
    expect(() => createInspection('nope')).toThrow()
  })
})

describe('Walkaround component', () => {
  it('inspects checkpoints and summarises', async () => {
    const onComplete = vi.fn()
    render(<Walkaround scenarioId="track" onComplete={onComplete} />)
    const finish = screen.getByRole('button', { name: 'Finish walkaround' })
    expect(finish).toBeDisabled()

    for (const p of CHECKPOINTS) {
      await userEvent.click(screen.getByRole('button', { name: p.label }))
      if (p.id === 'right_track') {
        expect(screen.getByTestId('observation')).toHaveTextContent('track shoe bolt is missing')
      }
      await userEvent.click(
        screen.getByRole('button', { name: p.id === 'right_track' ? 'Defect' : 'OK' }),
      )
    }
    expect(screen.getByRole('button', { name: 'Right track' })).toHaveAttribute('data-verdict', 'defect')
    expect(screen.getByText('Checked 8 of 8')).toBeInTheDocument()

    await userEvent.click(finish)
    expect(screen.getByRole('status')).toHaveTextContent('Walkaround passed')
    expect(screen.getByText(/Tag the machine out/)).toBeInTheDocument()
    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ passed: true }))

    await userEvent.click(screen.getByRole('button', { name: 'Start again' }))
    expect(screen.getByText('Checked 0 of 8')).toBeInTheDocument()
  })
})

