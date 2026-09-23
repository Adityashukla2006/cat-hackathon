export const SITE_CENTER = [12.8575, 77.5649] // Anjanapura quarries, south Bengaluru
export const OPERATOR_MACHINE_ID = 1
export const OPERATOR_ID = 1

export const MACHINES = {
  1: { name: 'EX-01', kind: 'Excavator', color: '#ffcd11' },
  2: { name: 'WL-02', kind: 'Wheel loader', color: '#38bdf8' },
}

export const HAZARD_LABELS = {
  soft_ground: 'Soft ground',
  spill: 'Spill',
  overhead_line: 'Overhead line',
}

/** Merge a hazard_pin message into the pin list: replace by id, drop inactive pins. */
export function mergePin(pins, pin) {
  const rest = pins.filter((p) => p.id !== pin.id)
  return pin.active ? [...rest, pin] : rest
}

/** Turn a hazard_warning for one machine into an alert-shaped object for the banner. */
export function warningToAlert(msg, minute) {
  const label = HAZARD_LABELS[msg.pin.kind] ?? 'Hazard'
  return {
    id: `hazard-${msg.pin.id}-${minute}`,
    local: true,
    minute,
    kind: 'hazard_proximity',
    severity: 'warning',
    message: `${label} ${Math.round(msg.distance_m)} m ahead: ${msg.pin.description} Slow down and keep clear.`,
    acknowledged: false,
  }
}
