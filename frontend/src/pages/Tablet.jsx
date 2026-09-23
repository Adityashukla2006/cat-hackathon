import { useEffect, useState } from 'react'
import AheadBehindBar from '../components/AheadBehindBar'
import ShadowTimeline from '../components/ShadowTimeline'
import { getJson } from '../lib/api'
import { useTelemetry } from '../lib/useTelemetry'

const OPERATOR_MACHINE_ID = 1
const SHIFT_START_HOUR = 7

export function clock(minute) {
  const h = SHIFT_START_HOUR + Math.floor(minute / 60)
  const m = minute % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

function Tile({ label, value, warn = false }) {
  return (
    <div className={`rounded-2xl p-4 ${warn ? 'bg-alert-red' : 'bg-neutral-900'}`}>
      <p className="text-base font-semibold text-neutral-300">{label}</p>
      <p className="text-3xl font-black">{value}</p>
    </div>
  )
}

export default function Tablet({ createSocket }) {
  const [timeline, setTimeline] = useState(null)
  const [error, setError] = useState(null)
  const { status, minute, machines, delta, send } = useTelemetry(
    createSocket ? { createSocket } : undefined,
  )
  const me = machines[OPERATOR_MACHINE_ID]

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const data = await getJson('/demo/shadow')
        if (alive) setTimeline(data)
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [])

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-3xl font-black">EX-01</h1>
        <p className="text-3xl font-black tabular-nums" aria-label="Shift clock">
          {clock(minute)}
        </p>
      </header>

      <AheadBehindBar delta={delta} />
      {error ? (
        <p role="alert" className="rounded-2xl bg-alert-red p-4 text-xl font-bold">
          Shadow unavailable: {error}
        </p>
      ) : (
        <ShadowTimeline timeline={timeline} minute={minute} currentSeq={me?.task_seq ?? null} />
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <Tile label="Engine" value={me?.engine_on ? 'On' : 'Off'} />
        <Tile
          label="Seatbelt"
          value={me?.seatbelt === false ? 'Unbuckled' : 'Buckled'}
          warn={Boolean(me?.engine_on && me?.seatbelt === false)}
        />
        <Tile label="Load" value={me ? `${Math.round(me.load_pct)}%` : '–'} />
        <Tile label="Fuel" value={me ? `${Math.round(me.fuel_rate_lph)} L/h` : '–'} />
      </div>

      <div className="flex gap-4">
        {status === 'paused' ? (
          <button
            onClick={() => send('resume')}
            className="min-h-16 flex-1 rounded-2xl bg-cat-yellow text-2xl font-black text-black"
          >
            Resume
          </button>
        ) : (
          <button
            onClick={() => send('pause')}
            disabled={status !== 'live'}
            className="min-h-16 flex-1 rounded-2xl bg-neutral-800 text-2xl font-black disabled:opacity-40"
          >
            Pause
          </button>
        )}
        <p className="flex min-h-16 flex-1 items-center justify-center rounded-2xl bg-neutral-900 text-xl font-semibold capitalize">
          {status}
        </p>
      </div>
    </main>
  )
}
