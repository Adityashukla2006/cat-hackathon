import { useEffect, useRef, useState } from 'react'
import VoiceButton from './VoiceButton'
import { postJson } from '../lib/api'
import { loadPosition, savePosition, snapToEdge, speak } from '../lib/chatWidget'

const BUBBLE = { width: 88, height: 88 }
const PANEL = { width: 360, height: 480 }
const DRAG_THRESHOLD = 6

function viewportSize() {
  return { width: window.innerWidth, height: window.innerHeight }
}

function defaultStorage() {
  try {
    return window.localStorage
  } catch {
    return null
  }
}

/**
 * Floating assistant. Drag it anywhere; it snaps to the nearest side edge and remembers where
 * it was. It minimizes when a safety alert fires, and goes voice-only while the machine works.
 */
export default function ChatWidget({
  alertActive = false,
  machineWorking = false,
  storage = defaultStorage(),
  startRecording,
  speakAnswers = speak,
}) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState(() => {
    const vp = viewportSize()
    return loadPosition(storage, snapToEdge({ x: vp.width, y: vp.height }, BUBBLE, vp))
  })
  const [messages, setMessages] = useState([])
  const [draft, setDraft] = useState('')
  const [busy, setBusy] = useState(false)
  const dragRef = useRef(null)
  const size = open ? PANEL : BUBBLE

  // a safety alert takes the screen: get out of the way
  useEffect(() => {
    if (alertActive) setOpen(false)
  }, [alertActive])

  // the open panel is bigger than the bubble: keep it on screen at the same edge
  useEffect(() => {
    setPos((p) => snapToEdge(p, open ? PANEL : BUBBLE, viewportSize()))
  }, [open])

  const onPointerDown = (e) => {
    dragRef.current = { startX: e.clientX, startY: e.clientY, origin: pos, moved: false }
    e.currentTarget.setPointerCapture?.(e.pointerId)
  }

  const onPointerMove = (e) => {
    const drag = dragRef.current
    if (!drag) return
    const dx = e.clientX - drag.startX
    const dy = e.clientY - drag.startY
    if (Math.hypot(dx, dy) > DRAG_THRESHOLD) drag.moved = true
    if (drag.moved) setPos({ x: drag.origin.x + dx, y: drag.origin.y + dy })
  }

  const onPointerUp = (e) => {
    const drag = dragRef.current
    dragRef.current = null
    if (!drag) return
    if (!drag.moved) {
      if (!open && alertActive) return // stay minimized while the alert is up
      setOpen((o) => !o)
      return
    }
    const snapped = snapToEdge(
      { x: drag.origin.x + (e.clientX - drag.startX), y: drag.origin.y + (e.clientY - drag.startY) },
      size,
      viewportSize(),
    )
    setPos(snapped)
    savePosition(storage, snapped)
  }

  const ask = async (question) => {
    const text = question.trim()
    if (!text || busy) return
    setMessages((m) => [...m, { role: 'you', text }])
    setDraft('')
    setBusy(true)
    try {
      const reply = await postJson('/chat', { message: text })
      setMessages((m) => [...m, { role: 'assistant', ...reply, text: reply.answer }])
      if (machineWorking) speakAnswers(reply.answer)
    } catch {
      setMessages((m) => [
        ...m,
        { role: 'assistant', text: 'Assistant unavailable. For safety questions, call your supervisor.' },
      ])
    } finally {
      setBusy(false)
    }
  }

  const style = { left: pos.x, top: pos.y, width: size.width, height: size.height }

  if (!open) {
    return (
      <button
        aria-label="Open assistant"
        data-testid="chat-bubble"
        className="fixed z-50 touch-none rounded-full bg-cat-yellow text-4xl shadow-2xl"
        style={style}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        💬
      </button>
    )
  }

  return (
    <section
      aria-label="Assistant"
      data-testid="chat-panel"
      className="fixed z-50 flex flex-col overflow-hidden rounded-2xl border-4 border-cat-yellow bg-neutral-950 shadow-2xl"
      style={style}
    >
      <header
        className="flex min-h-14 touch-none cursor-move items-center justify-between bg-cat-yellow px-4 text-black"
        data-testid="chat-handle"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
      >
        <span className="text-xl font-black">Assistant{machineWorking ? ' · voice only' : ''}</span>
        <span className="text-lg font-bold">Tap to close</span>
      </header>

      <ol className="flex-1 space-y-3 overflow-y-auto p-3" aria-live="polite">
        {messages.map((m, i) => (
          <li
            key={i}
            data-role={m.role}
            className={`rounded-xl p-3 text-lg ${
              m.role === 'you'
                ? 'ml-8 bg-neutral-800'
                : m.escalate_to_supervisor
                  ? 'mr-8 bg-alert-red font-bold'
                  : 'mr-8 bg-neutral-900'
            }`}
          >
            {m.text}
            {m.sources?.length > 0 && (
              <span className="mt-1 block text-sm text-neutral-400">From: {m.sources.join('; ')}</span>
            )}
          </li>
        ))}
        {busy && <li className="text-lg text-neutral-400">Thinking…</li>}
      </ol>

      <div className="border-t border-neutral-800 p-3">
        {machineWorking ? (
          <VoiceButton
            onTranscript={ask}
            idleLabel="Hold to ask"
            {...(startRecording ? { startRecording } : {})}
          />
        ) : (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault()
              ask(draft)
            }}
          >
            <input
              aria-label="Ask the assistant"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              className="min-h-14 flex-1 rounded-xl bg-neutral-800 px-3 text-lg"
            />
            <button className="min-h-14 rounded-xl bg-cat-yellow px-5 text-xl font-black text-black">
              Ask
            </button>
          </form>
        )}
      </div>
    </section>
  )
}
