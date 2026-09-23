import { useState } from 'react'
import {
  CHECKPOINTS,
  createInspection,
  inspect,
  observe,
  summarize,
} from '../lib/walkaround'

function MachineOutline() {
  // top-down excavator: tracks either side, house in the middle, boom forward (up)
  return (
    <svg viewBox="0 0 100 100" className="absolute inset-0 h-full w-full" aria-hidden="true">
      <rect x="6" y="30" width="16" height="56" rx="4" fill="#333" />
      <rect x="78" y="30" width="16" height="56" rx="4" fill="#333" />
      <rect x="24" y="36" width="52" height="46" rx="6" fill="#ffcd11" />
      <rect x="26" y="38" width="14" height="14" rx="2" fill="#111" />
      <rect x="45" y="6" width="10" height="34" rx="3" fill="#c9a20e" />
      <rect x="40" y="2" width="20" height="8" rx="2" fill="#777" />
    </svg>
  )
}

/** Tap each checkpoint, look at what's there, and mark it OK or Defect. */
export default function Walkaround({ scenarioId = 'leak', onComplete }) {
  const [inspection, setInspection] = useState(() => createInspection(scenarioId))
  const [selected, setSelected] = useState(null)
  const [summary, setSummary] = useState(null)
  const point = CHECKPOINTS.find((p) => p.id === selected)
  const progress = Object.keys(inspection.verdicts).length

  const decide = (verdict) => {
    setInspection((prev) => inspect(prev, selected, verdict))
    setSelected(null)
  }

  const finish = () => {
    const result = summarize(inspection)
    setSummary(result)
    onComplete?.(result)
  }

  const restart = () => {
    setInspection(createInspection(scenarioId))
    setSummary(null)
    setSelected(null)
  }

  if (summary) {
    return (
      <section role="status" className="rounded-2xl border-4 border-cat-yellow bg-neutral-900 p-5">
        <p className="text-3xl font-black">
          {summary.passed ? 'Walkaround passed' : 'Walkaround not passed'} · {summary.score} / 100
        </p>
        {summary.found.length > 0 && (
          <p className="mt-2 text-xl font-bold text-alert-red">
            Defects found. Tag the machine out and tell your supervisor before operating.
          </p>
        )}
        {summary.missed.length > 0 && (
          <p className="mt-2 text-xl font-bold text-amber-300">
            Missed: {summary.missed.map((id) => CHECKPOINTS.find((p) => p.id === id).label).join(', ')}
          </p>
        )}
        {summary.falseAlarms.length > 0 && (
          <p className="mt-2 text-lg">False alarms: {summary.falseAlarms.length}</p>
        )}
        {!summary.ordered && summary.complete && (
          <p className="mt-2 text-lg">Tip: walk around in one direction so you don't skip a side.</p>
        )}
        <button
          onClick={restart}
          className="mt-4 min-h-16 w-full rounded-2xl bg-cat-yellow text-2xl font-black text-black"
        >
          Start again
        </button>
      </section>
    )
  }

  return (
    <section aria-label="Walkaround inspection" className="flex flex-col gap-4">
      <p className="text-xl font-bold">
        Checked {progress} of {CHECKPOINTS.length}
      </p>
      <div className="relative mx-auto aspect-square w-full max-w-md rounded-2xl bg-neutral-800">
        <MachineOutline />
        {CHECKPOINTS.map((p) => {
          const verdict = inspection.verdicts[p.id]
          return (
            <button
              key={p.id}
              aria-label={p.label}
              data-verdict={verdict ?? 'none'}
              onClick={() => setSelected(p.id)}
              className={`absolute h-14 w-14 -translate-x-1/2 -translate-y-1/2 rounded-full border-4 text-xl font-black ${
                verdict === 'defect'
                  ? 'border-white bg-alert-red'
                  : verdict === 'ok'
                    ? 'border-white bg-emerald-500'
                    : 'border-cat-yellow bg-black/70'
              }`}
              style={{ left: `${p.x}%`, top: `${p.y}%` }}
            >
              {verdict === 'defect' ? '!' : verdict === 'ok' ? '✓' : ''}
            </button>
          )
        })}
      </div>

      {point && (
        <div aria-label="Checkpoint" className="rounded-2xl bg-neutral-900 p-5">
          <p className="text-2xl font-black">{point.label}</p>
          <p className="text-lg text-neutral-300">Check: {point.check}</p>
          <p className="mt-2 text-xl font-semibold" data-testid="observation">
            You see: {observe(inspection, point.id)}
          </p>
          <div className="mt-4 flex gap-4">
            <button
              onClick={() => decide('ok')}
              className="min-h-16 flex-1 rounded-2xl bg-emerald-500 text-2xl font-black text-black"
            >
              OK
            </button>
            <button
              onClick={() => decide('defect')}
              className="min-h-16 flex-1 rounded-2xl bg-alert-red text-2xl font-black"
            >
              Defect
            </button>
          </div>
        </div>
      )}

      <button
        onClick={finish}
        disabled={progress < CHECKPOINTS.length}
        className="min-h-16 rounded-2xl bg-cat-yellow text-2xl font-black text-black disabled:opacity-40"
      >
        Finish walkaround
      </button>
    </section>
  )
}
