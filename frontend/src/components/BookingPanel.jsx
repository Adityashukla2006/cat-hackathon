import { useEffect, useState } from 'react'
import { getJson, postJson } from '../lib/api'
import { OPERATOR_ID } from '../lib/site'

const MAX_SLOTS = 6

export function formatSlot(iso) {
  const d = new Date(iso)
  const day = d.toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: 'UTC' })
  const time = d.toLocaleTimeString('en-GB', { hour: '2-digit', minute: '2-digit', timeZone: 'UTC' })
  return `${day} ${time}`
}

/** Book an instructor session for a topic from the mocked calendar. */
export default function BookingPanel({ topic, topicTitle }) {
  const [open, setOpen] = useState(false)
  const [slots, setSlots] = useState(null)
  const [bookings, setBookings] = useState([])
  const [error, setError] = useState(null)

  const loadBookings = async () => {
    try {
      setBookings(await getJson(`/operators/${OPERATOR_ID}/bookings`))
    } catch {
      // the list is informational
    }
  }

  useEffect(() => {
    loadBookings()
  }, [])

  const showSlots = async () => {
    setOpen(true)
    setError(null)
    try {
      setSlots(await getJson(`/instructors/slots?topic=${encodeURIComponent(topic)}`))
    } catch (e) {
      setError(e.message)
    }
  }

  const book = async (slot) => {
    setError(null)
    try {
      await postJson('/bookings', {
        operator_id: OPERATOR_ID,
        topic,
        slot_start: slot.slot_start,
        instructor: slot.instructor,
      })
      setOpen(false)
      await loadBookings()
    } catch {
      await showSlots() // refresh first: it clears old errors
      setError('That slot was just taken. Pick another.')
    }
  }

  const cancel = async (id) => {
    await postJson(`/bookings/${id}/cancel`, {}).catch(() => {})
    await loadBookings()
  }

  return (
    <div aria-label="Instructor booking" className="mt-4 space-y-3">
      {bookings.map((b) => (
        <div key={b.id} role="status" className="flex items-center gap-3 rounded-xl bg-emerald-800 p-3">
          <p className="flex-1 text-lg font-bold">
            Booked: {b.instructor}, {formatSlot(b.slot_start)}
          </p>
          <button onClick={() => cancel(b.id)} className="min-h-12 rounded-xl bg-black/40 px-4 font-bold">
            Cancel
          </button>
        </div>
      ))}
      {!open ? (
        <button
          onClick={showSlots}
          className="min-h-16 w-full rounded-2xl bg-cat-yellow text-xl font-black text-black"
        >
          Book an instructor for {topicTitle}
        </button>
      ) : (
        <div className="grid gap-2">
          {slots === null && !error && <p className="text-lg">Checking the calendar…</p>}
          {slots?.length === 0 && <p className="text-lg">No free slots this week. Ask your supervisor.</p>}
          {slots?.slice(0, MAX_SLOTS).map((s) => (
            <button
              key={`${s.instructor}-${s.slot_start}`}
              onClick={() => book(s)}
              className="min-h-14 rounded-xl bg-neutral-800 px-4 text-left text-lg font-bold"
            >
              {formatSlot(s.slot_start)} · {s.instructor}
            </button>
          ))}
        </div>
      )}
      {error && <p role="alert" className="text-lg text-amber-300">{error}</p>}
    </div>
  )
}
