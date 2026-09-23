import { LIMITS, forwardKinematics } from '../lib/armKinematics'
import { TASKS, createRun, phaseLabel, scoreRun, stepRun } from '../lib/simTasks'

// brute-force an arm pose whose bucket tip satisfies `predicate`
function findArm(predicate, extra = () => true) {
  for (let boom = LIMITS.boom[0]; boom <= LIMITS.boom[1]; boom += 0.05) {
    for (let stick = LIMITS.stick[0]; stick <= LIMITS.stick[1]; stick += 0.05) {
      for (let bucket = LIMITS.bucket[0]; bucket <= LIMITS.bucket[1]; bucket += 0.05) {
        const arm = { boom, stick, bucket, swing: 0 }
        if (predicate(forwardKinematics(arm).bucketTip) && extra(arm)) return arm
      }
    }
  }
  throw new Error('no pose found')
}

const REST = { boom: 0.4, stick: -1.6, bucket: -0.8, swing: 0 }
const near = (p, q, tol) => Math.hypot(p.x - q.x, p.y - q.y) <= tol

describe('reach task', () => {
  const onTarget = findArm((tip) => near(tip, TASKS.reach.target, 0.2))

  it('needs the tip held on target for the hold time', () => {
    let run = createRun('reach')
    run = stepRun(run, REST, 2)
    expect(phaseLabel(run)).toBe('Move to the target')
    run = stepRun(run, onTarget, 0.5)
    expect(phaseLabel(run)).toBe('Hold steady')
    expect(run.done).toBe(false)
    run = stepRun(run, onTarget, 0.6)
    expect(run.done).toBe(true)
    expect(phaseLabel(run)).toBe('Done')
  })

  it('resets the hold timer when the tip leaves the target', () => {
    let run = createRun('reach')
    run = stepRun(run, onTarget, 0.8)
    run = stepRun(run, REST, 0.1)
    run = stepRun(run, onTarget, 0.5)
    expect(run.done).toBe(false)
  })

  it('scores a fast, smooth, accurate run highly', () => {
    let run = createRun('reach')
    run = stepRun(run, onTarget, 0.6, { boom: -1 })
    run = stepRun(run, onTarget, 0.6, { boom: -1 })
    const result = scoreRun(run)
    expect(result.passed).toBe(true)
    expect(result.score).toBeGreaterThanOrEqual(85)
    expect(result.stars).toBe(3)
  })
})

describe('dig task', () => {
  const task = TASKS.dig
  const inTrench = (tip) => tip.x > task.trench.minX + 0.3 && tip.x < task.trench.maxX - 0.3
  const shallow = findArm((tip) => inTrench(tip) && tip.y < -0.2 && tip.y > -0.8)
  const deep = findArm(
    (tip) => inTrench(tip) && tip.y < -1.6 && tip.y > -2.2,
    (arm) => arm.bucket > -1.2,
  )
  const curledDeep = findArm(
    (tip) => inTrench(tip) && tip.y < -1.0,
    (arm) => arm.bucket <= task.curledBelow,
  )
  const lifted = findArm((tip) => tip.y > 1.2, (arm) => arm.bucket <= task.curledBelow)

  it('walks through lower, dig, curl, lift', () => {
    let run = createRun('dig')
    run = stepRun(run, shallow, 1)
    expect(phaseLabel(run)).toBe('Dig to depth')
    run = stepRun(run, deep, 1)
    expect(phaseLabel(run)).toBe('Curl the bucket')
    run = stepRun(run, curledDeep, 1)
    expect(phaseLabel(run)).toBe('Lift clear')
    run = stepRun(run, lifted, 1)
    expect(run.done).toBe(true)
  })

  it('cannot skip the depth step', () => {
    let run = createRun('dig')
    run = stepRun(run, shallow, 1)
    run = stepRun(run, lifted, 1)
    expect(run.done).toBe(false)
  })
})

describe('grade task', () => {
  const task = TASKS.grade
  const far = findArm((tip) => tip.x >= task.from + 0.1 && Math.abs(tip.y) < 0.1)
  const middle = findArm((tip) => Math.abs(tip.x - 6) < 0.2 && Math.abs(tip.y) < 0.1)
  const middleHigh = findArm((tip) => Math.abs(tip.x - 6) < 0.2 && tip.y > 0.8 && tip.y < 1.2)
  const nearFlag = findArm((tip) => tip.x <= task.to - 0.1 && Math.abs(tip.y) < 0.1)

  it('counts accuracy only while dragging', () => {
    let run = createRun('grade')
    run = stepRun(run, REST, 1)
    expect(run.samples).toBe(0)
    run = stepRun(run, far, 1)
    run = stepRun(run, middle, 1)
    run = stepRun(run, middleHigh, 1)
    run = stepRun(run, nearFlag, 1)
    expect(run.done).toBe(true)
    expect(scoreRun(run).accuracy).toBe(75)
  })
})

describe('scoring', () => {
  it('penalises the bucket coming too close to the machine once per entry', () => {
    const inCab = findArm((tip) => tip.x < 1.0 && tip.y < 2.4)
    let run = createRun('reach')
    run = stepRun(run, inCab, 0.1)
    run = stepRun(run, inCab, 0.1)
    expect(run.penalties.cab).toBe(1)
    run = stepRun(run, REST, 0.1)
    run = stepRun(run, inCab, 0.1)
    expect(run.penalties.cab).toBe(2)
    expect(scoreRun(run).passed).toBe(false)
  })

  it('counts lever reversals against smoothness', () => {
    let run = createRun('reach')
    for (let i = 0; i < 6; i++) run = stepRun(run, REST, 0.1, { boom: i % 2 ? 1 : -1 })
    expect(run.reversals).toBe(5)
    run = stepRun(run, REST, 0.1, { boom: 0.1 })
    expect(run.reversals).toBe(5)
  })

  it('gives zero for an unfinished run', () => {
    expect(scoreRun(createRun('dig'))).toMatchObject({ score: 0, stars: 0, passed: false })
    expect(() => createRun('nope')).toThrow()
  })
})
