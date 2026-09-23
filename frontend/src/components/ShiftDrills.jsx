import { useEffect, useState } from 'react'
import { getJson, postJson } from '../lib/api'
import { OPERATOR_ID } from '../lib/site'

const SHIFT_START_HOUR = 7

function clock(minute) {
  const h = SHIFT_START_HOUR + Math.floor(minute / 60)
  return `${String(h).padStart(2, '0')}:${String(minute % 60).padStart(2, '0')}`
}

function DrillCard({ shiftId, drill, onPractice }) {
  const [choice, setChoice] = useState(null)
  const [result, setResult] = useState(null)

  const answer = async (index) => {
    setChoice(index)
    try {
      setResult(
        await postJson(`/shifts/${shiftId}/drills/${drill.id}/answer`, {
          operator_id: OPERATOR_ID,
          answer: index,
        }),
      )
    } catch {
      setResult({ correct: false, correct_option: '', explanation: 'Could not check the answer.' })
    }
  }

  return (
    <article aria-label={drill.title} className="rounded-2xl bg-neutral-900 p-5">
      <p className="text-lg font-bold text-cat-yellow">
        {clock(drill.minute)} · {drill.title}
      </p>
      <p className="mt-1 text-xl">{drill.scenario}</p>
      <p className="mt-3 text-xl font-black">{drill.question}</p>
      <div className="mt-3 grid gap-2">
        {drill.options.map((opt, i) => {
          const picked = choice === i && result
          return (
            <button
              key={opt}
              disabled={Boolean(result)}
              onClick={() => answer(i)}
              className={`min-h-14 rounded-xl px-4 text-left text-lg font-bold ${
                picked ? (result.correct ? 'bg-emerald-500 text-black' : 'bg-alert-red') : 'bg-neutral-800'
              }`}
            >
              {opt}
            </button>
          )
        })}
      </div>
      {result && (
        <div role="status" className="mt-3 text-lg">
          <p className="font-black">{result.correct ? 'Right.' : `Better: ${result.correct_option}`}</p>
          <p>{result.explanation}</p>
          {drill.practice && (
            <button
              onClick={() => onPractice(drill.practice)}
              className="mt-3 min-h-14 w-full rounded-2xl bg-cat-yellow text-xl font-black text-black"
            >
              Practice in the simulator
            </button>
          )}
        </div>
      )}
    </article>
  )
}

/** Drills built from what actually happened on the operator's shift. */
export default function ShiftDrills({ shiftId = 1, onPractice = () => {} }) {
  const [drills, setDrills] = useState(null)
  const [error, setError] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const body = await getJson(`/shifts/${shiftId}/drills`)
        if (alive) setDrills(body)
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [shiftId])

  if (error) return <p role="alert">Drills unavailable: {error}</p>
  if (!drills) return <p className="text-xl">Loading your shift…</p>
  if (drills.length === 0) {
    return <p className="text-xl">Nothing to review from this shift yet. Nice work.</p>
  }
  return (
    <section aria-label="From your shift" className="flex flex-col gap-4">
      {drills.map((d) => (
        <DrillCard key={d.id} shiftId={shiftId} drill={d} onPractice={onPractice} />
      ))}
    </section>
  )
}
