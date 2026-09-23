import { useRef, useState } from 'react'

const SIZE = 176
const KNOB = 72
const TRAVEL = (SIZE - KNOB) / 2

/** Glove-sized virtual joystick. Reports x/y in -1..1 (y = +1 pushed forward), springs to center. */
export default function Joystick({ label, onChange }) {
  const [pos, setPos] = useState({ x: 0, y: 0 })
  const padRef = useRef(null)
  const activeRef = useRef(false)

  const update = (event) => {
    const rect = padRef.current.getBoundingClientRect()
    let dx = (event.clientX - (rect.left + rect.width / 2)) / TRAVEL
    let dy = -(event.clientY - (rect.top + rect.height / 2)) / TRAVEL
    const mag = Math.hypot(dx, dy)
    if (mag > 1) {
      dx /= mag
      dy /= mag
    }
    const next = { x: dx, y: dy }
    setPos(next)
    onChange?.(next)
  }

  const release = () => {
    activeRef.current = false
    setPos({ x: 0, y: 0 })
    onChange?.({ x: 0, y: 0 })
  }

  return (
    <div className="flex flex-col items-center gap-2">
      <div
        ref={padRef}
        role="slider"
        aria-label={label}
        aria-valuetext={`x ${pos.x.toFixed(2)}, y ${pos.y.toFixed(2)}`}
        tabIndex={0}
        className="relative touch-none rounded-full border-4 border-neutral-600 bg-neutral-900"
        style={{ width: SIZE, height: SIZE }}
        onPointerDown={(e) => {
          activeRef.current = true
          e.currentTarget.setPointerCapture?.(e.pointerId)
          update(e)
        }}
        onPointerMove={(e) => activeRef.current && update(e)}
        onPointerUp={release}
        onPointerCancel={release}
      >
        <div
          data-testid={`${label}-knob`}
          className="absolute rounded-full bg-cat-yellow shadow-lg"
          style={{
            width: KNOB,
            height: KNOB,
            left: TRAVEL + pos.x * TRAVEL,
            top: TRAVEL - pos.y * TRAVEL,
          }}
        />
      </div>
      <span className="text-lg font-bold">{label}</span>
    </div>
  )
}
