import { useCallback, useEffect, useState } from 'react'
import SiteMap from '../components/SiteMap'
import { describeDelta } from '../components/AheadBehindBar'
import { getJson, postJson } from '../lib/api'
import { HAZARD_LABELS, MACHINES, OPERATOR_MACHINE_ID, mergePin } from '../lib/site'
import { useTelemetry } from '../lib/useTelemetry'
import { clock } from './Tablet'

const SHIFT_ID = 1
const SEVERITY_DOT = { critical: 'bg-alert-red', warning: 'bg-amber-400', info: 'bg-sky-500' }

function MachineCard({ frame, extra }) {
  const machine = MACHINES[frame.machine_id]
  return (
    <div className="rounded-2xl bg-neutral-900 p-4" aria-label={`${machine?.name} status`}>
      <p className="text-2xl font-black" style={{ color: machine?.color }}>
        {machine?.name} · {machine?.kind}
      </p>
      <p className="text-lg">
        {frame.engine_on ? (frame.idle ? 'Idle' : 'Working') : 'Engine off'} · {Math.round(frame.speed_kph)} km/h ·
        load {Math.round(frame.load_pct)}%
      </p>
      {extra}
    </div>
  )
}

/** Supervisor console: the whole site live, with alerts, incidents, and hazard pins to manage. */
export default function Supervisor({ createSocket }) {
  const [alerts, setAlerts] = useState([])
  const [incidents, setIncidents] = useState([])
  const [pins, setPins] = useState([])
  const [warnings, setWarnings] = useState([])
  const [fatigue, setFatigue] = useState(null)
  const [replan, setReplan] = useState(null)

  const onMessage = useCallback((msg) => {
    if (msg.type === 'alert') setAlerts((prev) => [msg.alert, ...prev])
    if (msg.type === 'incident_logged') setIncidents((prev) => [...prev, msg.incident])
    if (msg.type === 'hazard_pin') setPins((prev) => mergePin(prev, msg.pin))
    if (msg.type === 'hazard_warning') setWarnings((prev) => [msg, ...prev].slice(0, 5))
    if (msg.type === 'fatigue') setFatigue(msg.score)
    if (msg.type === 'replan') setReplan(msg.replan)
    if (msg.type === 'replay_status' && msg.state === 'started') {
      setAlerts([])
      setIncidents([])
      setWarnings([])
      setReplan(null)
    }
  }, [])

  const { status, minute, machines, delta, send } = useTelemetry({
    onMessage,
    ...(createSocket ? { createSocket } : {}),
  })

  useEffect(() => {
    let alive = true
    const load = async () => {
      const [a, i, p] = await Promise.allSettled([
        getJson(`/shifts/${SHIFT_ID}/alerts`),
        getJson(`/shifts/${SHIFT_ID}/incidents`),
        getJson('/hazards'),
      ])
      if (!alive) return
      // anything that already arrived live is newer than these snapshots
      if (a.status === 'fulfilled') {
        setAlerts((prev) => [...prev, ...[...a.value].reverse().filter((x) => !prev.some((y) => y.id === x.id))])
      }
      if (i.status === 'fulfilled') {
        setIncidents((prev) => [...i.value.filter((x) => !prev.some((y) => y.id === x.id)), ...prev])
      }
      if (p.status === 'fulfilled') {
        setPins((prev) => [...prev, ...p.value.filter((x) => !prev.some((y) => y.id === x.id))])
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [])

  const updatePin = async (pin, action) => {
    try {
      const updated = await postJson(`/hazards/${pin.id}/${action}`, {})
      setPins((prev) => mergePin(prev, updated))
    } catch {
      // the next hazard_pin broadcast will correct the view
    }
  }

  const operatorFrame = machines[OPERATOR_MACHINE_ID]
  const openAlerts = alerts.filter((a) => !a.acknowledged).length

  return (
    <main className="mx-auto grid max-w-7xl gap-4 p-4 lg:grid-cols-3">
      <header className="flex items-center justify-between lg:col-span-3">
        <h1 className="text-3xl font-black">Supervisor console</h1>
        <div className="flex items-center gap-4">
          <p className="text-3xl font-black tabular-nums" aria-label="Site clock">
            {clock(minute)}
          </p>
          <button
            onClick={() => send(status === 'paused' ? 'resume' : 'pause')}
            disabled={status !== 'live' && status !== 'paused'}
            className="min-h-12 rounded-xl bg-neutral-800 px-5 text-lg font-bold disabled:opacity-40"
          >
            {status === 'paused' ? 'Resume replay' : 'Pause replay'}
          </button>
        </div>
      </header>

      <div className="flex flex-col gap-4 lg:col-span-2">
        <SiteMap machines={machines} pins={pins} height={440} />
        <div className="grid gap-4 md:grid-cols-2">
          {Object.values(machines)
            .sort((x, y) => x.machine_id - y.machine_id)
            .map((frame) => (
              <MachineCard
                key={frame.machine_id}
                frame={frame}
                extra={
                  frame.machine_id === OPERATOR_MACHINE_ID && (
                    <p className="text-lg" data-testid="operator-status">
                      Task {operatorFrame?.task_seq ?? '–'} · {describeDelta(delta).label} · fatigue{' '}
                      {fatigue == null ? '–' : `${Math.round(fatigue * 100)}%`}
                    </p>
                  )
                }
              />
            ))}
        </div>
        {replan && (
          <p className="rounded-2xl bg-neutral-900 p-4 text-lg">
            <span className="font-black text-cat-yellow">Latest replan: </span>
            {replan.explanation}
          </p>
        )}
      </div>

      <aside className="flex flex-col gap-4">
        <section aria-label="Alerts" className="rounded-2xl bg-neutral-900 p-4">
          <h2 className="text-2xl font-black">Alerts ({openAlerts} open)</h2>
          <ul className="mt-2 max-h-72 space-y-2 overflow-y-auto">
            {alerts.map((a) => (
              <li key={a.id} className="flex gap-2 text-base">
                <span className={`mt-1.5 h-3 w-3 shrink-0 rounded-full ${SEVERITY_DOT[a.severity]}`} />
                <span>
                  <span className="font-bold">{clock(a.minute)}</span> {a.message}
                  {a.acknowledged && <span className="text-neutral-500"> (ack)</span>}
                </span>
              </li>
            ))}
            {alerts.length === 0 && <li className="text-neutral-400">No alerts yet.</li>}
          </ul>
        </section>

        <section aria-label="Incidents" className="rounded-2xl bg-neutral-900 p-4">
          <h2 className="text-2xl font-black">Incident reports</h2>
          <ul className="mt-2 space-y-2">
            {incidents.map((i) => (
              <li key={i.id} className="text-base">
                <span className="font-bold">
                  {clock(i.minute)} · {i.report.category} · {i.report.severity}
                </span>
                <br />
                {i.report.summary}
              </li>
            ))}
            {incidents.length === 0 && <li className="text-neutral-400">None reported.</li>}
          </ul>
        </section>

        <section aria-label="Hazards" className="rounded-2xl bg-neutral-900 p-4">
          <h2 className="text-2xl font-black">Site hazards</h2>
          <ul className="mt-2 space-y-3">
            {pins.map((p) => (
              <li key={p.id} className="text-base">
                <p className="font-bold">
                  {HAZARD_LABELS[p.kind] ?? p.kind} · {Math.round(p.confidence * 100)}% confidence
                </p>
                <p>{p.description}</p>
                <div className="mt-1 flex gap-2">
                  <button
                    onClick={() => updatePin(p, 'confirm')}
                    className="min-h-12 flex-1 rounded-xl bg-neutral-800 font-bold"
                  >
                    Reconfirm
                  </button>
                  <button
                    onClick={() => updatePin(p, 'clear')}
                    className="min-h-12 flex-1 rounded-xl bg-neutral-800 font-bold"
                  >
                    Clear
                  </button>
                </div>
              </li>
            ))}
            {pins.length === 0 && <li className="text-neutral-400">No active hazards.</li>}
          </ul>
          {warnings.length > 0 && (
            <ul className="mt-3 space-y-1 text-base text-amber-300" aria-label="Proximity warnings">
              {warnings.map((w, idx) => (
                <li key={idx}>
                  {MACHINES[w.machine_id]?.name} warned {Math.round(w.distance_m)} m from{' '}
                  {HAZARD_LABELS[w.pin.kind] ?? w.pin.kind}
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </main>
  )
}
