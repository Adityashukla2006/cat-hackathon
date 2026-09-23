import { useState } from 'react'
import { getJson } from '../lib/api'

/** End-of-shift handover for the next crew, generated on demand. */
export default function HandoverPanel({ shiftId = 1 }) {
  const [handover, setHandover] = useState(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState(null)

  const load = async () => {
    setLoading(true)
    setError(null)
    try {
      setHandover(await getJson(`/shifts/${shiftId}/handover`))
    } catch (e) {
      setError(e.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <section aria-label="Handover" className="rounded-2xl bg-neutral-900 p-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-2xl font-black">Handover</h2>
        <button
          onClick={load}
          disabled={loading}
          className="min-h-12 rounded-xl bg-cat-yellow px-5 text-lg font-black text-black disabled:opacity-40"
        >
          {loading ? 'Writing…' : handover ? 'Refresh' : 'Prepare handover'}
        </button>
      </div>
      {error && <p role="alert">Handover unavailable: {error}</p>}
      {handover && (
        <div className="mt-3 space-y-3 text-base">
          <p className="text-xl font-bold">{handover.headline}</p>
          {handover.carry_over.length > 0 && (
            <div>
              <p className="font-black text-cat-yellow">Carry over</p>
              <ul className="list-disc pl-5">
                {handover.carry_over.map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {handover.watch_outs.length > 0 && (
            <div>
              <p className="font-black text-alert-red">Watch out</p>
              <ul className="list-disc pl-5">
                {handover.watch_outs.map((w) => (
                  <li key={w}>{w}</li>
                ))}
              </ul>
            </div>
          )}
          <p className="text-neutral-400">
            Done: {handover.done.length} tasks · incidents: {handover.incidents.length} · open alerts:{' '}
            {handover.open_alerts.length}
          </p>
        </div>
      )}
    </section>
  )
}
