import { useEffect, useState } from 'react'
import { getJson } from '../lib/api'
import { OPERATOR_ID } from '../lib/site'

/** The Coach's picks for this operator, from their recorded shifts and practice. */
export default function CoachCard({ onOpenLesson, children }) {
  const [advice, setAdvice] = useState(null)

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const body = await getJson(`/operators/${OPERATOR_ID}/coach`)
        if (alive) setAdvice(body)
      } catch {
        // coaching is optional; the lesson list still works without it
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [])

  if (!advice) return null
  return (
    <section aria-label="Coach" className="rounded-2xl border-4 border-cat-yellow bg-neutral-900 p-5">
      <p className="text-2xl font-black text-cat-yellow">Your coach</p>
      <p className="mt-1 text-xl">{advice.note}</p>
      {advice.recommendations.length > 0 && (
        <ol className="mt-3 grid gap-2">
          {advice.recommendations.map((r, i) => (
            <li key={r.lesson_id}>
              <button
                onClick={() => onOpenLesson(r.lesson_id)}
                className="min-h-16 w-full rounded-xl bg-neutral-800 px-4 text-left"
              >
                <span className="block text-xl font-black">
                  {i + 1}. {r.title}
                </span>
                <span className="text-base text-neutral-300">Because: {r.reasons.join('; ')}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
      {advice.suggest_instructor && children?.(advice.suggest_instructor)}
    </section>
  )
}
