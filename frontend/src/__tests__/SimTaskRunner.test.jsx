import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import SimTaskRunner from '../components/SimTaskRunner'
import { LIMITS, forwardKinematics } from '../lib/armKinematics'
import { TASKS } from '../lib/simTasks'

let simProps
vi.mock('../components/JoystickSim', () => ({
  default: (props) => {
    simProps = props
    return <div data-testid="sim">{props.overlay?.((p) => p)}</div>
  },
}))

function armAtReachTarget() {
  for (let boom = LIMITS.boom[0]; boom <= LIMITS.boom[1]; boom += 0.05) {
    for (let stick = LIMITS.stick[0]; stick <= LIMITS.stick[1]; stick += 0.05) {
      const arm = { boom, stick, bucket: -0.8, swing: 0 }
      const tip = forwardKinematics(arm).bucketTip
      if (Math.hypot(tip.x - TASKS.reach.target.x, tip.y - TASKS.reach.target.y) < 0.2) return arm
    }
  }
  throw new Error('no pose')
}

describe('SimTaskRunner', () => {
  it('lists the tasks and starts one with its overlay', async () => {
    render(<SimTaskRunner />)
    expect(screen.getAllByRole('button')).toHaveLength(3)
    await userEvent.click(screen.getByRole('button', { name: /Dig a trench cycle/ }))
    expect(screen.getByTestId('phase')).toHaveTextContent('Lower into the trench')
    expect(screen.getByTestId('overlay-dig')).toBeInTheDocument()
  })

  it('scores a completed run and reports it', async () => {
    const onComplete = vi.fn()
    render(<SimTaskRunner onComplete={onComplete} />)
    await userEvent.click(screen.getByRole('button', { name: /Reach the target/ }))
    const arm = armAtReachTarget()
    act(() => simProps.onTick(arm, 0.6, {}))
    expect(screen.getByTestId('phase')).toHaveTextContent('Hold steady')
    act(() => simProps.onTick(arm, 0.6, {}))

    expect(screen.getByRole('status')).toHaveTextContent('/ 100')
    expect(screen.getByTestId('timer')).toHaveTextContent('1.2 s')
    expect(onComplete).toHaveBeenCalledWith(expect.objectContaining({ taskId: 'reach', passed: true }))

    await userEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(screen.queryByRole('status')).not.toBeInTheDocument()
    expect(screen.getByTestId('timer')).toHaveTextContent('0.0 s')
  })

  it('goes back to the task list after a run', async () => {
    render(<SimTaskRunner />)
    await userEvent.click(screen.getByRole('button', { name: /Reach the target/ }))
    const arm = armAtReachTarget()
    act(() => simProps.onTick(arm, 1.2, {}))
    act(() => simProps.onTick(arm, 0.1, {}))
    await userEvent.click(screen.getByRole('button', { name: 'Other tasks' }))
    expect(screen.getByRole('button', { name: /Grade level/ })).toBeInTheDocument()
  })
})
