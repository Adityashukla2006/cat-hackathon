import { useEffect, useRef, useState } from 'react'
import Joystick from './Joystick'
import {
  INITIAL_STATE,
  applyControls,
  bucketReach,
  forwardKinematics,
  mapIsoControls,
} from '../lib/armKinematics'

// SVG viewport in meters: x from -2 to 11, y from -4 to 8 (flipped so y points up)
const VIEW = { minX: -2, maxY: 8, width: 13, height: 12 }
const MAX_DT = 0.1

const toSvg = (p) => ({ x: p.x - VIEW.minX, y: VIEW.maxY - p.y })

/** 2D excavator arm driven by two ISO-pattern joysticks. */
export default function JoystickSim({ initialState = INITIAL_STATE, onStateChange }) {
  const [state, setState] = useState(initialState)
  const leversRef = useRef({ left: { x: 0, y: 0 }, right: { x: 0, y: 0 } })
  const onStateChangeRef = useRef(onStateChange)
  onStateChangeRef.current = onStateChange

  useEffect(() => {
    let frame
    let last = null
    const tick = (now) => {
      const dt = last === null ? 0 : Math.min((now - last) / 1000, MAX_DT)
      last = now
      const { left, right } = leversRef.current
      if (dt > 0 && (left.x || left.y || right.x || right.y)) {
        setState((prev) => {
          const next = applyControls(prev, mapIsoControls(left, right), dt)
          onStateChangeRef.current?.(next)
          return next
        })
      }
      frame = requestAnimationFrame(tick)
    }
    frame = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(frame)
  }, [])

  const joints = forwardKinematics(state)
  const pts = [joints.base, joints.boomTip, joints.stickTip, joints.bucketTip].map(toSvg)
  const { reach, depth } = bucketReach(state)
  const ground = toSvg({ x: 0, y: 0 }).y

  return (
    <section aria-label="Joystick simulator" className="flex flex-col gap-4">
      <svg
        viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
        className="w-full rounded-2xl bg-sky-950"
        role="img"
        aria-label="Excavator arm"
      >
        <rect x={0} y={ground} width={VIEW.width} height={VIEW.height - ground} fill="#5b4636" />
        <rect x={toSvg({ x: -1.8, y: 0 }).x} y={ground - 1.8} width={3} height={1.8} fill="#ffcd11" />
        <polyline
          data-testid="arm"
          points={pts.map((p) => `${p.x},${p.y}`).join(' ')}
          fill="none"
          stroke="#ffcd11"
          strokeWidth={0.35}
          strokeLinejoin="round"
          strokeLinecap="round"
        />
        {pts.map((p, i) => (
          <circle key={i} cx={p.x} cy={p.y} r={0.22} fill="#111" />
        ))}
      </svg>
      <div className="flex justify-between text-xl font-bold tabular-nums">
        <span data-testid="reach">Reach {reach.toFixed(1)} m</span>
        <span data-testid="depth">Depth {depth.toFixed(1)} m</span>
      </div>
      <div className="flex justify-around">
        <Joystick label="Left stick" onChange={(v) => (leversRef.current.left = v)} />
        <Joystick label="Right stick" onChange={(v) => (leversRef.current.right = v)} />
      </div>
    </section>
  )
}
