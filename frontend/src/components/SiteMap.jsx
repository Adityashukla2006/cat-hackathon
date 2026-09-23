import { Circle, CircleMarker, MapContainer, TileLayer, Tooltip } from 'react-leaflet'
import { HAZARD_LABELS, MACHINES, SITE_CENTER } from '../lib/site'

/** Live site map: machines as dots, hazard pins as geofence circles that fade with confidence. */
export default function SiteMap({ machines, pins = [], focusMachineId = null, height = 320 }) {
  return (
    <section aria-label="Site map" className="overflow-hidden rounded-2xl" style={{ height }}>
      <MapContainer center={SITE_CENTER} zoom={17} scrollWheelZoom={false} className="h-full w-full">
        <TileLayer
          attribution="&copy; OpenStreetMap contributors"
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        {pins.map((pin) => (
          <Circle
            key={`pin-${pin.id}`}
            center={[pin.lat, pin.lon]}
            radius={pin.radius_m}
            pathOptions={{
              color: '#ff3b30',
              fillColor: '#ff3b30',
              fillOpacity: 0.15 + 0.35 * pin.confidence,
              weight: 3,
            }}
          >
            <Tooltip permanent direction="top">
              {HAZARD_LABELS[pin.kind] ?? pin.kind} · {Math.round(pin.confidence * 100)}%
            </Tooltip>
          </Circle>
        ))}
        {Object.values(machines).map((frame) => {
          const machine = MACHINES[frame.machine_id] ?? { name: `#${frame.machine_id}`, color: '#fff' }
          const focused = frame.machine_id === focusMachineId
          return (
            <CircleMarker
              key={`machine-${frame.machine_id}`}
              center={[frame.lat, frame.lon]}
              radius={focused ? 12 : 9}
              pathOptions={{ color: '#000', fillColor: machine.color, fillOpacity: 1, weight: 3 }}
            >
              <Tooltip permanent direction="right">
                {machine.name}
              </Tooltip>
            </CircleMarker>
          )
        })}
      </MapContainer>
    </section>
  )
}
