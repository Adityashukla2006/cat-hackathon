// Joystick simulator tasks and scoring. Pure functions: createRun -> stepRun per frame -> scoreRun.
import { forwardKinematics } from './armKinematics'

// bucket tip inside this box is too close to the machine: the cab, or undercutting the tracks
export const CAB_ZONE = { maxX: 1.2, maxY: 2.6 }
export const MAX_SAFE_DEPTH = 2.5
const REVERSAL_LEVER = 0.2
const JOINTS = ['boom', 'stick', 'bucket', 'swing']

export const TASKS = {
  reach: {
    id: 'reach',
    title: 'Reach the target',
    instructions: 'Put the bucket tip on the yellow target and hold it there for 1 second.',
    target: { x: 6.5, y: 0.6 },
    tolerance: 0.4,
    holdS: 1,
    parS: 12,
  },
  dig: {
    id: 'dig',
    title: 'Dig a trench cycle',
    instructions: 'Dig 1.5 m deep inside the trench, curl the bucket to fill it, then lift clear.',
    trench: { minX: 5, maxX: 7.5 },
    depth: 1.5,
    curledBelow: -1.6,
    liftY: 1.0,
    parS: 25,
  },
  grade: {
    id: 'grade',
    title: 'Grade level',
    instructions: 'Drag the bucket tip along the ground from the far flag back to the near flag.',
    from: 8,
    to: 4,
    tolerance: 0.3,
    parS: 20,
  },
}

export function createRun(taskId) {
  if (!TASKS[taskId]) throw new Error(`unknown task ${taskId}`)
  return {
    taskId,
    elapsedS: 0,
    phase: 0,
    holdS: 0,
    samples: 0,
    onTarget: 0,
    reversals: 0,
    lastSign: {},
    penalties: { cab: 0, overDig: 0 },
    wasInCab: false,
    wasOverDig: false,
    done: false,
  }
}

export function phaseLabel(run) {
  const labels = {
    reach: ['Move to the target', 'Hold steady'],
    dig: ['Lower into the trench', 'Dig to depth', 'Curl the bucket', 'Lift clear'],
    grade: ['Place the bucket at the far flag', 'Drag along the ground'],
  }[run.taskId]
  return run.done ? 'Done' : labels[run.phase]
}

function countReversals(run, controls) {
  let reversals = 0
  const lastSign = { ...run.lastSign }
  for (const joint of JOINTS) {
    const lever = controls?.[joint] ?? 0
    if (Math.abs(lever) < REVERSAL_LEVER) continue
    const sign = Math.sign(lever)
    if (lastSign[joint] && lastSign[joint] !== sign) reversals += 1
    lastSign[joint] = sign
  }
  return { reversals, lastSign }
}

function safety(run, tip) {
  const inCab = tip.x < CAB_ZONE.maxX && tip.y < CAB_ZONE.maxY
  const overDig = -tip.y > MAX_SAFE_DEPTH
  return {
    penalties: {
      cab: run.penalties.cab + (inCab && !run.wasInCab ? 1 : 0),
      overDig: run.penalties.overDig + (overDig && !run.wasOverDig ? 1 : 0),
    },
    wasInCab: inCab,
    wasOverDig: overDig,
  }
}

function advanceReach(run, tip, dt) {
  const task = TASKS.reach
  const on = Math.hypot(tip.x - task.target.x, tip.y - task.target.y) <= task.tolerance
  const holdS = on ? run.holdS + dt : 0
  return { phase: on ? 1 : 0, holdS, done: holdS >= task.holdS, onTarget: on }
}

function advanceDig(run, tip, arm) {
  const task = TASKS.dig
  const inTrench = tip.x >= task.trench.minX && tip.x <= task.trench.maxX
  let phase = run.phase
  if (phase === 0 && inTrench && tip.y < 0) phase = 1
  if (phase === 1 && inTrench && -tip.y >= task.depth) phase = 2
  if (phase === 2 && arm.bucket <= task.curledBelow) phase = 3
  const done = phase === 3 && tip.y >= task.liftY && arm.bucket <= task.curledBelow
  return { phase, done, onTarget: inTrench }
}

function advanceGrade(run, tip) {
  const task = TASKS.grade
  const onGround = Math.abs(tip.y) <= task.tolerance
  let phase = run.phase
  if (phase === 0 && tip.x >= task.from && onGround) phase = 1
  const done = phase === 1 && tip.x <= task.to
  // accuracy only counts while dragging
  return { phase, done, onTarget: onGround, counts: phase === 1 }
}

/** Advance a run by one frame of `dt` seconds with the arm in `arm` under `controls`. */
export function stepRun(run, arm, dt, controls = {}) {
  if (run.done) return run
  const tip = forwardKinematics(arm).bucketTip
  const { reversals, lastSign } = countReversals(run, controls)
  let progress
  if (run.taskId === 'reach') progress = advanceReach(run, tip, dt)
  else if (run.taskId === 'dig') progress = advanceDig(run, tip, arm)
  else progress = advanceGrade(run, tip)
  const counts = progress.counts ?? true

  return {
    ...run,
    ...safety(run, tip),
    elapsedS: run.elapsedS + dt,
    phase: progress.phase,
    holdS: progress.holdS ?? run.holdS,
    done: progress.done,
    samples: run.samples + (counts ? 1 : 0),
    onTarget: run.onTarget + (counts && progress.onTarget ? 1 : 0),
    reversals: run.reversals + reversals,
    lastSign,
  }
}

/** 0-100 score: speed vs par, accuracy, smoothness, minus safety penalties. */
export function scoreRun(run) {
  const task = TASKS[run.taskId]
  const speed = run.done ? Math.max(0, Math.min(1, (2 * task.parS - run.elapsedS) / task.parS)) : 0
  const accuracy = run.samples ? run.onTarget / run.samples : 0
  const smoothness = Math.max(0, 1 - run.reversals / 10)
  const penalty = run.penalties.cab * 25 + run.penalties.overDig * 15
  const raw = run.done ? 40 * speed + 30 * accuracy + 30 * smoothness : 0
  const score = Math.max(0, Math.round(raw - penalty))
  return {
    taskId: run.taskId,
    passed: run.done && run.penalties.cab === 0,
    score,
    stars: score >= 85 ? 3 : score >= 60 ? 2 : score > 0 ? 1 : 0,
    timeS: Math.round(run.elapsedS * 10) / 10,
    accuracy: Math.round(accuracy * 100),
    smoothness: Math.round(smoothness * 100),
    penalties: run.penalties,
  }
}
