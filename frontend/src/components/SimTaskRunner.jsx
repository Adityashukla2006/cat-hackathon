import { useRef, useState } from 'react'
import JoystickSim from './JoystickSim'
import { CAB_ZONE, TASKS, createRun, phaseLabel, scoreRun, stepRun } from '../lib/simTasks'

function TaskOverlay({ taskId, toSvg }) {
  const task = TASKS[taskId]
  const cab = toSvg({ x: -2, y: CAB_ZONE.maxY })
  const cabZone = (
    <rect
      x={cab.x}
      y={cab.y}
      width={CAB_ZONE.maxX + 2}
      height={CAB_ZONE.maxY + 4}
      fill="#ff3b30"
      opacity={0.15}
    />
  )
  if (taskId === 'reach') {
    const t = toSvg(task.target)
    return (
      <g data-testid="overlay-reach">
        {cabZone}
        <circle cx={t.x} cy={t.y} r={task.tolerance} fill="#ffcd11" opacity={0.6} />
      </g>
    )
  }
  if (taskId === 'dig') {
    const top = toSvg({ x: task.trench.minX, y: 0 })
    return (
      <g data-testid="overlay-dig">
        {cabZone}
        <rect
          x={top.x}
          y={top.y}
          width={task.trench.maxX - task.trench.minX}
          height={task.depth}
          fill="#2a1d14"
          stroke="#ffcd11"
          strokeWidth={0.05}
          strokeDasharray="0.2 0.2"
        />
      </g>
    )
  }
  const far = toSvg({ x: task.from, y: 0 })
  const near = toSvg({ x: task.to, y: 0 })
  return (
    <g data-testid="overlay-grade">
      {cabZone}
      {[far, near].map((p) => (
        <line key={p.x} x1={p.x} y1={p.y} x2={p.x} y2={p.y - 1} stroke="#ffcd11" strokeWidth={0.1} />
      ))}
    </g>
  )
}

/** Pick a simulator task, run it against the joystick sim, and show the score card. */
export default function SimTaskRunner({ onComplete }) {
  const [taskId, setTaskId] = useState(null)
  const [attempt, setAttempt] = useState(0)
  const [view, setView] = useState(null) // { phase, elapsedS } for display
  const [result, setResult] = useState(null)
  const runRef = useRef(null)

  const start = (id) => {
    runRef.current = createRun(id)
    setTaskId(id)
    setResult(null)
    setView({ phase: phaseLabel(runRef.current), elapsedS: 0 })
    setAttempt((a) => a + 1)
  }

  const onTick = (arm, dt, controls) => {
    const run = runRef.current
    if (!run || run.done) return
    const next = stepRun(run, arm, dt, controls)
    runRef.current = next
    setView({ phase: phaseLabel(next), elapsedS: next.elapsedS })
    if (next.done) {
      const scored = scoreRun(next)
      setResult(scored)
      onComplete?.(scored)
    }
  }

  if (!taskId) {
    return (
      <section aria-label="Simulator tasks" className="grid gap-4 md:grid-cols-3">
        {Object.values(TASKS).map((t) => (
          <button
            key={t.id}
            onClick={() => start(t.id)}
            className="min-h-28 rounded-2xl bg-neutral-900 p-4 text-left"
          >
            <span className="block text-2xl font-black">{t.title}</span>
            <span className="text-base text-neutral-300">{t.instructions}</span>
          </button>
        ))}
      </section>
    )
  }

  const task = TASKS[taskId]
  return (
    <section aria-label={task.title} className="flex flex-col gap-4">
      <div className="flex items-center justify-between rounded-2xl bg-neutral-900 p-4">
        <div>
          <p className="text-2xl font-black">{task.title}</p>
          <p className="text-lg text-cat-yellow" data-testid="phase">
            {view?.phase}
          </p>
        </div>
        <p className="text-3xl font-black tabular-nums" data-testid="timer">
          {(view?.elapsedS ?? 0).toFixed(1)} s
        </p>
      </div>

      {result && (
        <div role="status" className="rounded-2xl border-4 border-cat-yellow bg-neutral-900 p-5">
          <p className="text-3xl font-black">
            {'★'.repeat(result.stars)}
            {'☆'.repeat(3 - result.stars)} {result.score} / 100
          </p>
          <p className="text-xl">
            {result.timeS} s · accuracy {result.accuracy}% · smoothness {result.smoothness}%
          </p>
          {result.penalties.cab > 0 && (
            <p className="text-xl font-bold text-alert-red">Bucket came too close to the machine (cab or tracks).</p>
          )}
          {result.penalties.overDig > 0 && (
            <p className="text-xl font-bold text-amber-300">Dug deeper than the safe limit.</p>
          )}
          <div className="mt-4 flex gap-4">
            <button
              onClick={() => start(taskId)}
              className="min-h-16 flex-1 rounded-2xl bg-cat-yellow text-2xl font-black text-black"
            >
              Try again
            </button>
            <button
              onClick={() => setTaskId(null)}
              className="min-h-16 flex-1 rounded-2xl bg-neutral-800 text-2xl font-black"
            >
              Other tasks
            </button>
          </div>
        </div>
      )}

      <JoystickSim
        key={attempt}
        onTick={onTick}
        overlay={(toSvg) => <TaskOverlay taskId={taskId} toSvg={toSvg} />}
      />
    </section>
  )
}
