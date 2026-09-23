const TASK_LABELS = {
  dig: 'Dig',
  load_truck: 'Load',
  trench: 'Trench',
  grade: 'Grade',
  stockpile: 'Stockpile',
}

function segmentClass(active, done) {
  if (active) return 'bg-cat-yellow text-black'
  if (done) return 'bg-neutral-700 text-neutral-400'
  return 'bg-neutral-800'
}

/** Horizontal strip of shadow tasks sized by expected (p50) minutes, with a "now" marker. */
export default function ShadowTimeline({ timeline, minute = 0, currentSeq = null }) {
  if (!timeline) {
    return <p className="rounded-2xl bg-neutral-900 p-6 text-xl">Loading shadow…</p>
  }
  const total = timeline.total_min.p50
  const nowPct = Math.min(minute / total, 1) * 100

  return (
    <section aria-label="Shadow timeline" className="rounded-2xl bg-neutral-900 p-4">
      <div className="mb-2 flex justify-between text-lg font-semibold">
        <span>Shadow shift</span>
        <span className="text-neutral-400">
          {Math.round(timeline.total_min.p10)}–{Math.round(timeline.total_min.p90)} min
        </span>
      </div>
      <div className="relative flex h-20 gap-1">
        {timeline.tasks.map((task) => {
          const active = task.seq === currentSeq
          const done = currentSeq !== null && task.seq < currentSeq
          const band = `${Math.round(task.duration_min.p10)}–${Math.round(task.duration_min.p90)}`
          return (
            <div
              key={task.seq}
              data-testid={`task-${task.seq}`}
              aria-current={active ? 'step' : undefined}
              title={`${task.description}: ${band} min`}
              className={`flex min-w-0 flex-col justify-center rounded-lg px-2 ${segmentClass(active, done)}`}
              style={{ width: `${(task.duration_min.p50 / total) * 100}%` }}
            >
              <span className="truncate text-lg font-bold">{TASK_LABELS[task.task_type]}</span>
              <span className="truncate text-sm">{Math.round(task.duration_min.p50)} min</span>
            </div>
          )
        })}
        <div
          data-testid="now-marker"
          className="pointer-events-none absolute -inset-y-1 w-1 rounded bg-white"
          style={{ left: `${nowPct}%` }}
        />
      </div>
      {timeline.risk_points.length > 0 && (
        <ul className="mt-3 space-y-1 text-base text-amber-300">
          {timeline.risk_points.map((r) => (
            <li key={r}>⚠ {r}</li>
          ))}
        </ul>
      )}
    </section>
  )
}
