import { useState } from 'react'
import LessonsHub from '../components/LessonsHub'
import SimTaskRunner from '../components/SimTaskRunner'
import Walkaround from '../components/Walkaround'
import { postJson } from '../lib/api'
import { OPERATOR_ID } from '../lib/site'

const TABS = [
  { id: 'lessons', label: 'Lessons' },
  { id: 'simulator', label: 'Joystick simulator' },
  { id: 'walkaround', label: 'Walkaround' },
]

function recordResult(activityId, score) {
  postJson('/training/results', {
    operator_id: OPERATOR_ID,
    activity_id: activityId,
    score: Math.max(0, Math.min(1, score / 100)),
  }).catch(() => {})
}

export default function Training() {
  const [tab, setTab] = useState('lessons')

  const practice = (what) => setTab(what === 'walkaround' ? 'walkaround' : 'simulator')

  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4">
      <h1 className="text-3xl font-black">Training</h1>
      <div role="tablist" className="flex gap-2">
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`min-h-14 flex-1 rounded-2xl text-xl font-black ${
              tab === t.id ? 'bg-cat-yellow text-black' : 'bg-neutral-900'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>
      {tab === 'lessons' && <LessonsHub onPractice={practice} />}
      {tab === 'simulator' && (
        <>
          <p className="text-lg text-neutral-300">
            ISO pattern. Left stick: stick in/out and swing. Right stick: boom up/down and bucket.
          </p>
          <SimTaskRunner onComplete={(r) => recordResult(`sim:${r.taskId}`, r.score)} />
        </>
      )}
      {tab === 'walkaround' && (
        <Walkaround onComplete={(r) => recordResult('walkaround:leak', r.score)} />
      )}
    </main>
  )
}
