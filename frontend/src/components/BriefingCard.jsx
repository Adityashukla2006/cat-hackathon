import { useState } from 'react'

/** The Planner's pre-shift briefing. Collapses to its headline once read. */
export default function BriefingCard({ briefing }) {
  const [open, setOpen] = useState(true)
  if (!briefing) return null

  return (
    <section aria-label="Pre-shift briefing" className="rounded-2xl bg-neutral-900 p-5">
      <button
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="flex min-h-12 w-full items-center justify-between text-left"
      >
        <span className="text-2xl font-black">{briefing.headline}</span>
        <span className="text-xl text-neutral-400">{open ? 'Hide' : 'Show'}</span>
      </button>
      {open && (
        <>
          <ul className="mt-3 space-y-1 text-lg">
            {briefing.key_risks.map((r) => (
              <li key={r}>⚠ {r}</li>
            ))}
          </ul>
          <p className="mt-3 text-xl font-bold text-cat-yellow">{briefing.focus_tip}</p>
        </>
      )}
    </section>
  )
}
