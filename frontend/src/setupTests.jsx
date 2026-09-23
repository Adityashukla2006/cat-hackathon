import { vi } from 'vitest'
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

// Leaflet needs a real browser layout; tests render its layers as plain elements instead
vi.mock('react-leaflet', () => {
  const layer = (name) =>
    function Layer({ children, center, radius, pathOptions }) {
      return (
        <div
          data-testid={name}
          data-center={center?.join(',')}
          data-radius={radius}
          data-fill-opacity={pathOptions?.fillOpacity}
        >
          {children}
        </div>
      )
    }
  return {
    MapContainer: layer('map'),
    TileLayer: () => null,
    Circle: layer('hazard-circle'),
    CircleMarker: layer('machine-marker'),
    Tooltip: ({ children }) => <span>{children}</span>,
  }
})
