import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import BookingPanel, { formatSlot } from '../components/BookingPanel'
import { getJson, postJson } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  getJson: vi.fn(),
  postJson: vi.fn(),
}))

const SLOTS = [
  { instructor: 'Maria Lopez', slot_start: '2026-09-28T08:00:00Z' },
  { instructor: 'Maria Lopez', slot_start: '2026-09-28T13:00:00Z' },
]
const BOOKING = {
  id: 5,
  operator_id: 1,
  instructor: 'Maria Lopez',
  topic: 'seatbelt',
  slot_start: '2026-09-28T08:00:00Z',
  status: 'confirmed',
}

describe('BookingPanel', () => {
  let booked
  beforeEach(() => {
    vi.clearAllMocks()
    booked = []
    getJson.mockImplementation(async (path) => (path.startsWith('/instructors') ? SLOTS : booked))
    postJson.mockImplementation(async (path) => {
      if (path === '/bookings') booked = [BOOKING]
      if (path.endsWith('/cancel')) booked = []
      return BOOKING
    })
  })

  it('formats slots in site time', () => {
    expect(formatSlot('2026-09-28T13:00:00Z')).toBe('Mon 28 Sept 13:00')
  })

  it('shows free slots, books one, and lists it', async () => {
    render(<BookingPanel topic="seatbelt" topicTitle="Seatbelt and cab safety" />)
    await userEvent.click(screen.getByRole('button', { name: 'Book an instructor for Seatbelt and cab safety' }))
    expect(getJson).toHaveBeenCalledWith('/instructors/slots?topic=seatbelt')
    await userEvent.click(await screen.findByRole('button', { name: /13:00 · Maria Lopez/ }))
    expect(postJson).toHaveBeenCalledWith('/bookings', {
      operator_id: 1,
      topic: 'seatbelt',
      slot_start: '2026-09-28T13:00:00Z',
      instructor: 'Maria Lopez',
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Booked: Maria Lopez')
  })

  it('cancels a booking', async () => {
    booked = [BOOKING]
    render(<BookingPanel topic="seatbelt" topicTitle="Seatbelt" />)
    await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }))
    expect(postJson).toHaveBeenCalledWith('/bookings/5/cancel', {})
    await waitFor(() => expect(screen.queryByRole('status')).not.toBeInTheDocument())
  })

  it('asks for another slot when one was just taken', async () => {
    postJson.mockImplementation(() => Promise.reject(new Error('409')))
    render(<BookingPanel topic="seatbelt" topicTitle="Seatbelt" />)
    await userEvent.click(screen.getByRole('button', { name: /Book an instructor/ }))
    await userEvent.click(await screen.findByRole('button', { name: /08:00 · Maria Lopez/ }))
    expect(await screen.findByRole('alert')).toHaveTextContent('just taken')
  })
})
