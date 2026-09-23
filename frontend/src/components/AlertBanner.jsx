const TITLES = {
  seatbelt: 'Buckle up',
  idle_deviation: 'Long idle',
  cycle_deviation: 'Behind plan',
  fuel_deviation: 'High fuel burn',
  fatigue: 'Take a break',
  hazard_proximity: 'Hazard ahead',
  speed: 'Slow down',
}

const TONES = {
  critical: 'bg-alert-red text-white animate-pulse',
  warning: 'bg-amber-400 text-black',
  info: 'bg-sky-600 text-white',
}

/** Full-width banner for the newest unacknowledged alert. One big button to acknowledge. */
export default function AlertBanner({ alerts, onAcknowledge }) {
  const open = alerts.filter((a) => !a.acknowledged)
  if (open.length === 0) return null
  const rank = { critical: 0, warning: 1, info: 2 }
  const [top] = [...open].sort((a, b) => rank[a.severity] - rank[b.severity] || b.minute - a.minute)

  return (
    <section
      role="alert"
      aria-live="assertive"
      data-severity={top.severity}
      className={`flex items-center gap-4 rounded-2xl p-5 ${TONES[top.severity]}`}
    >
      <div className="flex-1">
        <p className="text-3xl font-black">{TITLES[top.kind] ?? 'Alert'}</p>
        <p className="text-xl font-semibold">{top.message}</p>
        {open.length > 1 && <p className="mt-1 text-base font-bold">+{open.length - 1} more</p>}
      </div>
      <button
        onClick={() => onAcknowledge(top)}
        className="min-h-20 min-w-32 rounded-2xl bg-black/80 px-6 text-2xl font-black text-white"
      >
        Got it
      </button>
    </section>
  )
}
