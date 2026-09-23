import { useCallback, useEffect, useState } from 'react'
import AheadBehindBar from '../components/AheadBehindBar'
import AlertBanner from '../components/AlertBanner'
import BriefingCard from '../components/BriefingCard'
import ChatWidget from '../components/ChatWidget'
import ReplanCard from '../components/ReplanCard'
import ShadowTimeline from '../components/ShadowTimeline'
import SiteMap from '../components/SiteMap'
import VoiceButton from '../components/VoiceButton'
import { getJson, postJson } from '../lib/api'
import { MACHINES, OPERATOR_MACHINE_ID, mergePin, warningToAlert } from '../lib/site'
import { useTelemetry } from '../lib/useTelemetry'

const SHIFT_START_HOUR = 7

export function clock(minute) {
  const h = SHIFT_START_HOUR + Math.floor(minute / 60)
  const m = minute % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}

export function reorderTimeline(timeline, order) {
  if (!timeline || !order) return timeline
  const bySeq = Object.fromEntries(timeline.tasks.map((t) => [t.seq, t]))
  let start = 0
  const tasks = order.map((seq) => {
    const task = { ...bySeq[seq], start_min: start }
    start += task.duration_min.p50
    return task
  })
  return { ...timeline, tasks }
}

function Tile({ label, value, warn = false }) {
  return (
    <div className={`rounded-2xl p-4 ${warn ? 'bg-alert-red' : 'bg-neutral-900'}`}>
      <p className="text-base font-semibold text-neutral-300">{label}</p>
      <p className="text-3xl font-black">{value}</p>
    </div>
  )
}

/**
 * Operator tablet. The demo operator's machine (EX-01) gets the full shadow view; any other
 * machine (?machine=2) gets its site map, status, and hazard warnings.
 */
export default function Tablet({ machineId = OPERATOR_MACHINE_ID, createSocket, startRecording }) {
  const isOperator = machineId === OPERATOR_MACHINE_ID
  const [pins, setPins] = useState([])
  const [plan, setPlan] = useState(null)
  const [error, setError] = useState(null)
  const [alerts, setAlerts] = useState([])
  const [replan, setReplan] = useState(null)
  const [order, setOrder] = useState(null)
  const [fatigue, setFatigue] = useState(null)
  const [incident, setIncident] = useState(null)

  const onMessage = useCallback(
    (msg) => {
      if (msg.type === 'hazard_pin') setPins((prev) => mergePin(prev, msg.pin))
      if (msg.type === 'hazard_warning' && msg.machine_id === machineId) {
        setAlerts((prev) => [...prev, warningToAlert(msg, Date.now())])
      }
      if (msg.type === 'replay_status' && msg.state === 'started') {
        setAlerts([])
        setReplan(null)
        setOrder(null)
      }
      if (!isOperator) return
      // shift alerts, replans, fatigue, and incidents belong to the operator's machine
      if (msg.type === 'alert') setAlerts((prev) => [...prev, msg.alert])
      if (msg.type === 'replan') {
        setReplan(msg.replan)
        setOrder(msg.replan.new_order)
      }
      if (msg.type === 'fatigue') setFatigue(msg.score)
      if (msg.type === 'incident_logged') setIncident(msg.incident)
    },
    [isOperator, machineId],
  )

  const { status, minute, machines, delta, send } = useTelemetry({
    onMessage,
    ...(createSocket ? { createSocket } : {}),
  })
  const me = machines[machineId]

  useEffect(() => {
    let alive = true
    const load = async () => {
      try {
        const current = await getJson('/hazards')
        // pins that already arrived over the socket are newer than this snapshot
        if (alive) {
          setPins((prev) => {
            const seen = new Set(prev.map((p) => p.id))
            return [...prev, ...current.filter((p) => !seen.has(p.id))]
          })
        }
      } catch {
        // the map still works without pins; new ones arrive over the socket
      }
      if (!isOperator) return
      try {
        const data = await getJson('/demo/plan')
        if (alive) setPlan(data)
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [isOperator])

  const acknowledge = (alert) => {
    setAlerts((prev) => prev.map((a) => (a.id === alert.id ? { ...a, acknowledged: true } : a)))
    if (!alert.local) postJson(`/alerts/${alert.id}/ack`, {}).catch(() => {})
  }

  const timeline = reorderTimeline(plan?.timeline, order)
  const alertActive = alerts.some((a) => !a.acknowledged && a.severity !== 'info')
  const machineWorking = Boolean(
    me?.engine_on && !me?.idle && (me.speed_kph > 0.5 || me.load_pct > 5),
  )

  return (
    <main className="mx-auto flex max-w-5xl flex-col gap-4 p-4">
      <header className="flex items-center justify-between">
        <h1 className="text-3xl font-black">
          {MACHINES[machineId]?.name ?? `Machine ${machineId}`}
        </h1>
        <p className="text-3xl font-black tabular-nums" aria-label="Shift clock">
          {clock(minute)}
        </p>
      </header>

      <AlertBanner alerts={alerts} onAcknowledge={acknowledge} />
      <ReplanCard
        replan={replan}
        tasks={plan?.timeline.tasks}
        currentSeq={me?.task_seq ?? null}
        onDismiss={() => setReplan(null)}
      />
      {incident && (
        <p role="status" className="rounded-2xl bg-emerald-700 p-4 text-xl font-bold">
          Report logged: {incident.report.summary}
        </p>
      )}

      {isOperator && (
        <>
          <AheadBehindBar delta={delta} />
          {error ? (
            <p role="alert" className="rounded-2xl bg-alert-red p-4 text-xl font-bold">
              Shadow unavailable: {error}
            </p>
          ) : (
            <ShadowTimeline timeline={timeline} minute={minute} currentSeq={me?.task_seq ?? null} />
          )}
          {minute < 10 && <BriefingCard briefing={plan?.briefing} />}
        </>
      )}

      <div className="grid grid-cols-2 gap-4 md:grid-cols-5">
        <Tile label="Engine" value={me?.engine_on ? 'On' : 'Off'} />
        <Tile
          label="Seatbelt"
          value={me?.seatbelt === false ? 'Unbuckled' : 'Buckled'}
          warn={Boolean(me?.engine_on && me?.seatbelt === false)}
        />
        <Tile label="Load" value={me ? `${Math.round(me.load_pct)}%` : '–'} />
        <Tile label="Fuel" value={me ? `${Math.round(me.fuel_rate_lph)} L/h` : '–'} />
        {isOperator ? (
          <Tile
            label="Fatigue"
            value={fatigue == null ? '–' : `${Math.round(fatigue * 100)}%`}
            warn={fatigue >= 0.6}
          />
        ) : (
          <Tile label="Speed" value={me ? `${Math.round(me.speed_kph)} km/h` : '–'} />
        )}
      </div>

      <SiteMap machines={machines} pins={pins} focusMachineId={machineId} height={isOperator ? 260 : 420} />

      {isOperator && (
        <VoiceButton
          onTranscript={(transcript) => send('voice_note', { transcript })}
          {...(startRecording ? { startRecording } : {})}
        />
      )}

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

      <ChatWidget
        alertActive={alertActive}
        machineWorking={machineWorking}
        {...(startRecording ? { startRecording } : {})}
      />
    </main>
  )
}
