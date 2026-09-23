import { useRef, useState } from 'react'
import { postForm } from '../lib/api'

async function defaultRecorder() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
  const recorder = new MediaRecorder(stream)
  const chunks = []
  recorder.ondataavailable = (e) => chunks.push(e.data)
  recorder.start()
  return {
    stop: () =>
      new Promise((resolve) => {
        recorder.onstop = () => {
          stream.getTracks().forEach((t) => t.stop())
          resolve(new Blob(chunks, { type: recorder.mimeType || 'audio/webm' }))
        }
        recorder.stop()
      }),
  }
}

const LABELS = {
  idle: 'Hold to report',
  recording: 'Recording… release to send',
  sending: 'Sending…',
  sent: 'Report sent',
  error: 'Could not send. Try again',
}

/** Hold-to-talk incident report: records audio, transcribes it, hands back the text. */
export default function VoiceButton({
  onTranscript,
  startRecording = defaultRecorder,
  idleLabel = LABELS.idle,
}) {
  const [state, setState] = useState('idle')
  const recorderRef = useRef(null)

  const start = async () => {
    if (state === 'recording' || state === 'sending') return
    try {
      recorderRef.current = await startRecording()
      setState('recording')
    } catch {
      setState('error')
    }
  }

  const stop = async () => {
    const recorder = recorderRef.current
    recorderRef.current = null
    if (!recorder) return
    setState('sending')
    try {
      const blob = await recorder.stop()
      const form = new FormData()
      form.append('audio', blob, 'note.webm')
      const { transcript } = await postForm('/transcribe', form)
      onTranscript(transcript)
      setState('sent')
    } catch {
      setState('error')
    }
  }

  return (
    <button
      onPointerDown={start}
      onPointerUp={stop}
      onPointerLeave={stop}
      data-state={state}
      className={`min-h-24 w-full touch-none rounded-2xl text-2xl font-black ${
        state === 'recording' ? 'bg-alert-red text-white' : 'bg-white text-black'
      }`}
    >
      🎙 {state === 'idle' ? idleLabel : LABELS[state]}
    </button>
  )
}
