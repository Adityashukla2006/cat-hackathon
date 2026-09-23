import { act, fireEvent, render, screen } from '@testing-library/react'
import Joystick from '../components/Joystick'
import JoystickSim from '../components/JoystickSim'
import { INITIAL_STATE } from '../lib/armKinematics'

// jsdom reports a zero-size rect, so the pad center is (0, 0) and knob travel is 52px
const TRAVEL = 52

describe('Joystick', () => {
  it('reports normalized deflection and springs back on release', () => {
    const onChange = vi.fn()
    render(<Joystick label="Left stick" onChange={onChange} />)
    const pad = screen.getByRole('slider', { name: 'Left stick' })

    fireEvent.pointerDown(pad, { clientX: TRAVEL / 2, clientY: -TRAVEL / 2, pointerId: 1 })
    expect(onChange).toHaveBeenLastCalledWith({ x: 0.5, y: 0.5 })

    fireEvent.pointerMove(pad, { clientX: 3 * TRAVEL, clientY: 0, pointerId: 1 })
    expect(onChange).toHaveBeenLastCalledWith({ x: 1, y: -0 })

    fireEvent.pointerUp(pad, { pointerId: 1 })
    expect(onChange).toHaveBeenLastCalledWith({ x: 0, y: 0 })
    expect(pad).toHaveAttribute('aria-valuetext', 'x 0.00, y 0.00')
  })

  it('ignores moves without a press', () => {
    const onChange = vi.fn()
    render(<Joystick label="Right stick" onChange={onChange} />)
    fireEvent.pointerMove(screen.getByRole('slider'), { clientX: 10, clientY: 10 })
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('JoystickSim', () => {
  let frames
  beforeEach(() => {
    frames = []
    vi.spyOn(window, 'requestAnimationFrame').mockImplementation((cb) => {
      frames.push(cb)
      return frames.length
    })
    vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {})
  })
  afterEach(() => vi.restoreAllMocks())

  const runFrame = (time) => act(() => frames.at(-1)(time))

  it('lowers the boom when the right stick is pushed forward', () => {
    const onStateChange = vi.fn()
    render(<JoystickSim onStateChange={onStateChange} />)
    const arm = screen.getByTestId('arm').getAttribute('points')

    fireEvent.pointerDown(screen.getByRole('slider', { name: 'Right stick' }), {
      clientX: 0,
      clientY: -TRAVEL,
      pointerId: 1,
    })
    runFrame(0)
    runFrame(100)

    const state = onStateChange.mock.lastCall[0]
    expect(state.boom).toBeCloseTo(INITIAL_STATE.boom - 0.05, 6)
    expect(state.stick).toBe(INITIAL_STATE.stick)
    expect(screen.getByTestId('arm').getAttribute('points')).not.toBe(arm)
  })

  it('does not move while the sticks are centered and caps long frames', () => {
    const onStateChange = vi.fn()
    render(<JoystickSim onStateChange={onStateChange} />)
    runFrame(0)
    runFrame(5000)
    expect(onStateChange).not.toHaveBeenCalled()

    fireEvent.pointerDown(screen.getByRole('slider', { name: 'Left stick' }), {
      clientX: 0,
      clientY: -TRAVEL,
      pointerId: 1,
    })
    runFrame(10000)
    // a 5 s gap is capped to 0.1 s: stick moves 0.07 rad at full lever
    expect(onStateChange.mock.lastCall[0].stick).toBeCloseTo(INITIAL_STATE.stick + 0.07, 6)
  })

  it('shows reach and depth readouts', () => {
    render(<JoystickSim />)
    expect(screen.getByTestId('reach')).toHaveTextContent(/Reach \d+\.\d m/)
    expect(screen.getByTestId('depth')).toHaveTextContent(/Depth \d+\.\d m/)
  })
})
