import {
  ARM,
  INITIAL_STATE,
  LIMITS,
  RATES,
  applyControls,
  bucketReach,
  forwardKinematics,
  mapIsoControls,
} from '../lib/armKinematics'

const close = (a, b) => expect(a).toBeCloseTo(b, 6)

describe('forwardKinematics', () => {
  it('lays a straight horizontal arm end to end', () => {
    const { boomTip, stickTip, bucketTip } = forwardKinematics({ boom: 0, stick: 0, bucket: 0 })
    close(boomTip.x, ARM.boomLength)
    close(stickTip.x, ARM.boomLength + ARM.stickLength)
    close(bucketTip.x, ARM.boomLength + ARM.stickLength + ARM.bucketLength)
    close(bucketTip.y, ARM.base.y)
  })

  it('accumulates relative joint angles', () => {
    const { boomTip, stickTip } = forwardKinematics({ boom: Math.PI / 2, stick: -Math.PI / 2, bucket: 0 })
    close(boomTip.x, 0)
    close(boomTip.y, ARM.base.y + ARM.boomLength)
    close(stickTip.x, ARM.stickLength)
    close(stickTip.y, boomTip.y)
  })
})

describe('mapIsoControls', () => {
  it('maps the ISO pattern', () => {
    expect(mapIsoControls({ x: 0.5, y: 1 }, { x: -1, y: 1 })).toEqual({
      stick: 1,
      swing: 0.5,
      boom: -1,
      bucket: -1,
    })
  })

  it('ignores tiny lever movements', () => {
    const c = mapIsoControls({ x: 0.05, y: -0.09 }, { x: 0.02, y: 0.08 })
    expect(Object.values(c).every((v) => v === 0)).toBe(true)
  })
})

describe('applyControls', () => {
  it('moves joints at their rated speed', () => {
    const next = applyControls(INITIAL_STATE, { boom: 1, stick: -1, bucket: 0.5 }, 0.5)
    close(next.boom, INITIAL_STATE.boom + RATES.boom * 0.5)
    close(next.stick, INITIAL_STATE.stick - RATES.stick * 0.5)
    close(next.bucket, INITIAL_STATE.bucket + RATES.bucket * 0.25)
    close(next.swing, 0)
  })

  it('clamps to joint limits and clamps lever input', () => {
    const next = applyControls(INITIAL_STATE, { boom: 5, stick: -5 }, 60)
    expect(next.boom).toBe(LIMITS.boom[1])
    expect(next.stick).toBe(LIMITS.stick[0])
  })
})

describe('bucketReach', () => {
  it('reports depth only below ground', () => {
    expect(bucketReach({ boom: 0, stick: 0, bucket: 0 }).depth).toBe(0)
    const deep = bucketReach({ boom: -0.6, stick: -1.2, bucket: -0.5 })
    expect(deep.depth).toBeGreaterThan(0)
  })
})
