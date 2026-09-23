// Interactive pre-start walkaround. Checkpoints follow backend/guides/pre-start-walkaround.md,
// in clockwise order. Each scenario hides defects the operator should spot.

export const CHECKPOINTS = [
  {
    id: 'ground',
    label: 'Ground under the machine',
    x: 50,
    y: 88,
    check: 'Look for fresh puddles of oil, coolant, or fuel.',
    normal: 'Dry ground, no fresh drips.',
  },
  {
    id: 'left_track',
    label: 'Left track',
    x: 14,
    y: 55,
    check: 'Loose or missing shoes, damaged rollers, correct sag.',
    normal: 'Shoes tight, rollers turn, sag looks even.',
  },
  {
    id: 'bucket',
    label: 'Bucket and linkage',
    x: 50,
    y: 8,
    check: 'Teeth, cutting edge, pins, and retainers for cracks or wear.',
    normal: 'Teeth sharp, pins and retainers in place.',
  },
  {
    id: 'hydraulics',
    label: 'Boom cylinders and hoses',
    x: 50,
    y: 28,
    check: 'Leaks, rubbing, cracks, or bulges. Never feel for a leak with your hand.',
    normal: 'Hoses dry, no rubbing or bulges.',
  },
  {
    id: 'right_track',
    label: 'Right track',
    x: 86,
    y: 55,
    check: 'Loose or missing shoes, damaged rollers, correct sag.',
    normal: 'Shoes tight, rollers turn, sag looks even.',
  },
  {
    id: 'fluids',
    label: 'Engine bay fluids',
    x: 72,
    y: 78,
    check: 'Engine oil, coolant, and hydraulic oil at the sight gauges.',
    normal: 'All sight gauges in the green band.',
  },
  {
    id: 'lights',
    label: 'Lights, mirrors, camera, alarm',
    x: 28,
    y: 78,
    check: 'Clean and working, including the travel alarm.',
    normal: 'Clean, and the travel alarm sounds.',
  },
  {
    id: 'cab',
    label: 'Steps, seatbelt, extinguisher',
    x: 30,
    y: 40,
    check: 'Steps and handholds clear, seatbelt latches, extinguisher charged.',
    normal: 'Steps clear, belt latches, extinguisher gauge in the green.',
  },
]

export const SCENARIOS = {
  leak: {
    id: 'leak',
    defects: {
      hydraulics: 'Wet oil streak along the boom cylinder hose.',
      ground: 'Small fresh oil puddle under the boom.',
    },
  },
  track: {
    id: 'track',
    defects: { right_track: 'One track shoe bolt is missing and the shoe is loose.' },
  },
  cab: {
    id: 'cab',
    defects: { cab: 'Seatbelt buckle does not latch.' },
  },
}

export function createInspection(scenarioId = 'leak') {
  if (!SCENARIOS[scenarioId]) throw new Error(`unknown scenario ${scenarioId}`)
  return { scenarioId, verdicts: {}, order: [] }
}

/** What the operator sees when they look at a checkpoint in this scenario. */
export function observe(inspection, pointId) {
  const point = CHECKPOINTS.find((p) => p.id === pointId)
  return SCENARIOS[inspection.scenarioId].defects[pointId] ?? point.normal
}

/** Record a verdict ('ok' or 'defect'). Re-inspecting a point replaces its verdict. */
export function inspect(inspection, pointId, verdict) {
  if (!CHECKPOINTS.some((p) => p.id === pointId)) throw new Error(`unknown checkpoint ${pointId}`)
  if (verdict !== 'ok' && verdict !== 'defect') throw new Error(`bad verdict ${verdict}`)
  const order = inspection.order.includes(pointId)
    ? inspection.order
    : [...inspection.order, pointId]
  return { ...inspection, verdicts: { ...inspection.verdicts, [pointId]: verdict }, order }
}

function inClockwiseOrder(order) {
  const index = order.map((id) => CHECKPOINTS.findIndex((p) => p.id === id))
  // any rotation of the clockwise sequence counts: you can start anywhere
  const start = index[0]
  return index.every((v, i) => v === (start + i) % CHECKPOINTS.length)
}

export function summarize(inspection) {
  const defects = SCENARIOS[inspection.scenarioId].defects
  const inspected = Object.keys(inspection.verdicts)
  const found = inspected.filter((id) => defects[id] && inspection.verdicts[id] === 'defect')
  const missed = Object.keys(defects).filter((id) => inspection.verdicts[id] !== 'defect')
  const falseAlarms = inspected.filter((id) => !defects[id] && inspection.verdicts[id] === 'defect')
  const complete = inspected.length === CHECKPOINTS.length
  const ordered = complete && inClockwiseOrder(inspection.order)
  const score = Math.max(
    0,
    Math.round(
      (inspected.length / CHECKPOINTS.length) * 40 +
        (found.length / Object.keys(defects).length) * 50 +
        (ordered ? 10 : 0) -
        falseAlarms.length * 5,
    ),
  )
  return {
    complete,
    ordered,
    found,
    missed,
    falseAlarms,
    score,
    passed: complete && missed.length === 0,
    safeToOperate: missed.length === 0 && found.length === 0,
  }
}
