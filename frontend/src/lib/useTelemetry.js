import { useCallback, useEffect, useRef, useState } from 'react'
import { wsUrl } from './api'

const defaultSocket = (url) => new WebSocket(url)

/**
 * Subscribes to the replay WebSocket. Keeps the latest frame per machine, the current
 * minute, the ahead/behind delta, and every non-telemetry message for listeners.
 */
export function useTelemetry({ speed = 60, createSocket = defaultSocket, onMessage } = {}) {
  const [status, setStatus] = useState('connecting')
  const [minute, setMinute] = useState(0)
  const [machines, setMachines] = useState({})
  const [delta, setDelta] = useState(null)
  const socketRef = useRef(null)
  const onMessageRef = useRef(onMessage)
  onMessageRef.current = onMessage

  useEffect(() => {
    const socket = createSocket(wsUrl(`/ws/telemetry?speed=${speed}`))
    socketRef.current = socket
    socket.onopen = () => setStatus('live')
    socket.onclose = () => setStatus((s) => (s === 'finished' ? s : 'closed'))
    socket.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      if (msg.type === 'telemetry') {
        setMinute(msg.frame.minute)
        setMachines((prev) => ({ ...prev, [msg.frame.machine_id]: msg.frame }))
      } else if (msg.type === 'shadow_delta') {
        setDelta(msg.delta_min)
      } else if (msg.type === 'replay_status') {
        setStatus(msg.state === 'started' ? 'live' : msg.state)
      }
      onMessageRef.current?.(msg)
    }
    return () => socket.close()
  }, [speed, createSocket])

  const send = useCallback((action, extra = {}) => {
    const socket = socketRef.current
    if (socket && socket.readyState === 1) {
      socket.send(JSON.stringify({ action, ...extra }))
      if (action === 'pause') setStatus('paused')
      if (action === 'resume') setStatus('live')
    }
  }, [])

  return { status, minute, machines, delta, send }
}
