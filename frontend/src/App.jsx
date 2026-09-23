import { NavLink, Route, Routes, useSearchParams } from 'react-router-dom'
import Tablet from './pages/Tablet'
import Training from './pages/Training'

const links = [
  { to: '/', label: 'Tablet' },
  { to: '/training', label: 'Training' },
  { to: '/supervisor', label: 'Supervisor' },
]

function TabletRoute() {
  const [params] = useSearchParams()
  return <Tablet machineId={Number(params.get('machine')) || 1} />
}

function Placeholder({ title }) {
  return <h1 className="p-6 text-3xl font-bold">{title}</h1>
}

export default function App() {
  return (
    <div className="min-h-screen">
      <nav className="flex gap-2 bg-neutral-900 p-2">
        {links.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end
            className={({ isActive }) =>
              `min-h-12 rounded-lg px-5 py-3 text-lg font-semibold ${
                isActive ? 'bg-cat-yellow text-black' : 'text-white'
              }`
            }
          >
            {l.label}
          </NavLink>
        ))}
      </nav>
      <Routes>
        <Route path="/" element={<TabletRoute />} />
        <Route path="/training" element={<Training />} />
        <Route path="/supervisor" element={<Placeholder title="Supervisor" />} />
      </Routes>
    </div>
  )
}
