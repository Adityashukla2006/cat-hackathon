import '@testing-library/jest-dom/vitest'
import { cleanup } from '@testing-library/react'
import { afterEach } from 'vitest'

afterEach(() => cleanup())

// jsdom has no PointerEvent; a MouseEvent subclass keeps clientX/clientY and pointerId
if (!globalThis.PointerEvent) {
  class PointerEvent extends MouseEvent {
    constructor(type, init = {}) {
      super(type, init)
      this.pointerId = init.pointerId ?? 0
    }
  }
  globalThis.PointerEvent = PointerEvent
}
