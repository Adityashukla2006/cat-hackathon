import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import VoiceButton from '../components/VoiceButton'
import { postForm } from '../lib/api'

vi.mock('../lib/api', async (importOriginal) => ({
  ...(await importOriginal()),
  postForm: vi.fn(),
}))

const fakeRecorder = () =>
  vi.fn(async () => ({ stop: async () => new Blob(['audio'], { type: 'audio/webm' }) }))

describe('VoiceButton', () => {
  beforeEach(() => {
    postForm.mockReset()
  })

  it('records while held and sends the transcript on release', async () => {
    postForm.mockResolvedValue({ transcript: 'soft ground at the ramp' })
    const onTranscript = vi.fn()
    const startRecording = fakeRecorder()
    render(<VoiceButton onTranscript={onTranscript} startRecording={startRecording} />)
    const button = screen.getByRole('button')

    fireEvent.pointerDown(button)
    await waitFor(() => expect(button).toHaveAttribute('data-state', 'recording'))
    fireEvent.pointerUp(button)

    await waitFor(() => expect(onTranscript).toHaveBeenCalledWith('soft ground at the ramp'))
    expect(button).toHaveAttribute('data-state', 'sent')
    const [path, form] = postForm.mock.calls[0]
    expect(path).toBe('/transcribe')
    expect(form.get('audio')).toBeInstanceOf(Blob)
  })

  it('shows an error when the microphone is unavailable', async () => {
    const startRecording = vi.fn(async () => {
      throw new Error('denied')
    })
    render(<VoiceButton onTranscript={() => {}} startRecording={startRecording} />)
    fireEvent.pointerDown(screen.getByRole('button'))
    expect(await screen.findByText(/Could not send/)).toBeInTheDocument()
  })

  it('shows an error when transcription fails', async () => {
    postForm.mockImplementation(() => Promise.reject(new Error('502')))
    const onTranscript = vi.fn()
    render(<VoiceButton onTranscript={onTranscript} startRecording={fakeRecorder()} />)
    const button = screen.getByRole('button')
    fireEvent.pointerDown(button)
    await waitFor(() => expect(button).toHaveAttribute('data-state', 'recording'))
    fireEvent.pointerUp(button)
    expect(await screen.findByText(/Could not send/)).toBeInTheDocument()
    expect(onTranscript).not.toHaveBeenCalled()
  })
})
