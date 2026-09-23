import { act } from '@testing-library/react'

/** Minimal WebSocket stand-in. `createSocket` returns it; tests push server messages. */
export function makeFakeSocket() {
  const socket = {
    url: null,
    readyState: 0,
    sent: [],
    closed: false,
    onopen: null,
    onmessage: null,
    onclose: null,
    send(data) {
      this.sent.push(JSON.parse(data))
    },
    close() {
      this.closed = true
      this.readyState = 3
    },
    open() {
      act(() => {
        this.readyState = 1
        this.onopen?.()
      })
    },
    emit(message) {
      act(() => this.onmessage?.({ data: JSON.stringify(message) }))
    },
  }
  const createSocket = (url) => {
    socket.url = url
    return socket
  }
  return { socket, createSocket }
}

export function frame(overrides = {}) {
  return {
    shift_id: 1,
    machine_id: 1,
    minute: 0,
    lat: 40.695,
    lon: -89.589,
    engine_on: true,
    seatbelt: true,
    idle: false,
    fuel_rate_lph: 20,
    speed_kph: 2,
    load_pct: 60,
    task_seq: 1,
    ...overrides,
  }
}

export const TIMELINE = {
  shift_id: 1,
  total_min: { p10: 80, p50: 100, p90: 130 },
  risk_points: ['Task 2 (trench) could run long: up to 80 min vs 60 expected'],
  tasks: [
    {
      seq: 1,
      task_type: 'dig',
      description: 'Dig pit face A',
      duration_min: { p10: 30, p50: 40, p90: 50 },
      start_min: 0,
      expected_idle_min: 3,
      expected_fuel_l: 12,
      risk_score: null,
      status: 'pending',
    },
    {
      seq: 2,
      task_type: 'trench',
      description: 'Cut ditch',
      duration_min: { p10: 50, p50: 60, p90: 80 },
      start_min: 40,
      expected_idle_min: 5,
      expected_fuel_l: 15,
      risk_score: null,
      status: 'pending',
    },
  ],
}
