export const STORAGE_KEY = 'shadowShift.chatWidget.position'
export const EDGE_MARGIN = 12

/** Snap a widget of `size` to the nearer left/right edge and keep it fully on screen. */
export function snapToEdge(pos, size, viewport, margin = EDGE_MARGIN) {
  const centerX = pos.x + size.width / 2
  const x = centerX < viewport.width / 2 ? margin : viewport.width - size.width - margin
  const maxY = Math.max(margin, viewport.height - size.height - margin)
  const y = Math.min(Math.max(pos.y, margin), maxY)
  return { x, y }
}

export function loadPosition(storage, fallback) {
  try {
    const saved = JSON.parse(storage?.getItem(STORAGE_KEY) ?? 'null')
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) return saved
  } catch {
    // unreadable or blocked storage: use the default position
  }
  return fallback
}

export function savePosition(storage, pos) {
  try {
    storage?.setItem(STORAGE_KEY, JSON.stringify(pos))
  } catch {
    // storage can be unavailable (private mode); the widget still works
  }
}

export function speak(text) {
  try {
    if (typeof window !== 'undefined' && window.speechSynthesis) {
      window.speechSynthesis.cancel()
      window.speechSynthesis.speak(new SpeechSynthesisUtterance(text))
    }
  } catch {
    // speech is a nice-to-have
  }
}
