const RANGE_MIN = 30
const ON_TRACK_MIN = 2

export function describeDelta(delta) {
  if (delta === null || delta === undefined) return { label: 'Waiting for shift', tone: 'idle' }
  const mins = Math.round(Math.abs(delta))
  if (Math.abs(delta) < ON_TRACK_MIN) return { label: 'On track', tone: 'ok' }
  if (delta > 0) return { label: `${mins} min ahead`, tone: 'ahead' }
  return { label: `${mins} min behind`, tone: mins >= 10 ? 'late' : 'behind' }
}

const TONE_CLASSES = {
  idle: 'bg-neutral-600',
  ok: 'bg-emerald-500',
  ahead: 'bg-emerald-500',
  behind: 'bg-amber-400',
  late: 'bg-alert-red',
}

/** Centered bar: fills right when ahead of the shadow, left when behind. */
export default function AheadBehindBar({ delta }) {
  const { label, tone } = describeDelta(delta)
  const share = delta == null ? 0 : Math.min(Math.abs(delta), RANGE_MIN) / RANGE_MIN
  const width = `${share * 50}%`
  const side = delta > 0 ? { left: '50%' } : { right: '50%' }

  return (
    <section aria-label="Ahead or behind shadow" className="rounded-2xl bg-neutral-900 p-4">
      <p data-tone={tone} className="mb-3 text-center text-4xl font-black tracking-tight">
        {label}
      </p>
      <div className="relative h-8 overflow-hidden rounded-full bg-neutral-800">
        <div
          data-testid="delta-fill"
          className={`absolute inset-y-0 ${TONE_CLASSES[tone]}`}
          style={{ ...side, width }}
        />
        <div className="absolute inset-y-0 left-1/2 w-1 -translate-x-1/2 bg-white" />
      </div>
      <div className="mt-1 flex justify-between text-sm font-semibold text-neutral-400">
        <span>Behind</span>
        <span>Shadow</span>
        <span>Ahead</span>
      </div>
    </section>
  )
}
