// 2D excavator arm model. World units are meters, y points up, the boom pivot is the base.
// Angles are radians: boom from horizontal, stick relative to boom, bucket relative to stick.

export const ARM = {
  base: { x: 0, y: 1.8 },
  boomLength: 5.7,
  stickLength: 2.9,
  bucketLength: 1.5,
}

export const LIMITS = {
  boom: [-0.6, 1.2],
  stick: [-2.6, -0.5],
  bucket: [-2.2, 0.6],
  swing: [-Math.PI, Math.PI],
}

// max joint speed at full lever, rad/s
export const RATES = { boom: 0.5, stick: 0.7, bucket: 1.0, swing: 0.6 }

export const DEADZONE = 0.1

export const INITIAL_STATE = { boom: 0.4, stick: -1.6, bucket: -0.8, swing: 0 }

const clamp = (v, [lo, hi]) => Math.min(hi, Math.max(lo, v))

function advance(point, length, angle) {
  return { x: point.x + length * Math.cos(angle), y: point.y + length * Math.sin(angle) }
}

/** Joint positions for an arm state. */
export function forwardKinematics(state, arm = ARM) {
  const boomAngle = state.boom
  const stickAngle = boomAngle + state.stick
  const bucketAngle = stickAngle + state.bucket
  const boomTip = advance(arm.base, arm.boomLength, boomAngle)
  const stickTip = advance(boomTip, arm.stickLength, stickAngle)
  const bucketTip = advance(stickTip, arm.bucketLength, bucketAngle)
  return { base: arm.base, boomTip, stickTip, bucketTip, bucketAngle }
}

function applyDeadzone(v) {
  return Math.abs(v) < DEADZONE ? 0 : v
}

/**
 * ISO control pattern. Joystick axes are -1..1 with y = +1 pushed forward, x = +1 pushed right.
 * Left: forward/back = stick out/in, left/right = swing. Right: forward/back = boom down/up,
 * left/right = bucket curl/dump.
 */
export function mapIsoControls(left, right) {
  return {
    stick: applyDeadzone(left.y),
    swing: applyDeadzone(left.x),
    boom: -applyDeadzone(right.y),
    bucket: applyDeadzone(right.x),
  }
}

/** Integrate joint angles for `dt` seconds of lever input, respecting joint limits. */
export function applyControls(state, controls, dt) {
  const next = {}
  for (const joint of Object.keys(LIMITS)) {
    const lever = Math.max(-1, Math.min(1, controls[joint] ?? 0))
    next[joint] = clamp(state[joint] + lever * RATES[joint] * dt, LIMITS[joint])
  }
  return next
}

/** Horizontal reach and depth below ground (y = 0) of the bucket tip. */
export function bucketReach(state, arm = ARM) {
  const { bucketTip } = forwardKinematics(state, arm)
  return { reach: bucketTip.x - arm.base.x, depth: Math.max(0, -bucketTip.y) }
}
