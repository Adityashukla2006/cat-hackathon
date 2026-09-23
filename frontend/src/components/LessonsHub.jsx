import { useEffect, useState } from 'react'
import CoachCard from './CoachCard'
import { getJson, postJson } from '../lib/api'
import { OPERATOR_ID } from '../lib/site'

function useJson(path) {
  const [data, setData] = useState(null)
  const [error, setError] = useState(null)
  useEffect(() => {
    if (!path) return undefined
    let alive = true
    const load = async () => {
      try {
        const body = await getJson(path)
        if (alive) setData(body)
      } catch (e) {
        if (alive) setError(e.message)
      }
    }
    load()
    return () => {
      alive = false
    }
  }, [path])
  return { data, error, setData }
}

function Guide({ guideId }) {
  const { data } = useJson(`/guides/${guideId}`)
  if (!data) return <p className="text-lg">Loading guide…</p>
  return (
    <div aria-label="Guide" className="space-y-3 rounded-2xl bg-neutral-900 p-4">
      {data.sections.map((s) => (
        <div key={s.heading}>
          <p className="text-xl font-black">{s.heading}</p>
          <p className="whitespace-pre-line text-lg text-neutral-200">{s.text.replace(/\*\*/g, '')}</p>
        </div>
      ))}
    </div>
  )
}

function Quiz({ lesson }) {
  const [answers, setAnswers] = useState(() => lesson.questions.map(() => null))
  const [result, setResult] = useState(null)
  const [error, setError] = useState(null)
  const ready = answers.every((a) => a !== null)

  const submit = async () => {
    try {
      const body = await postJson(`/training/lessons/${lesson.id}/quiz`, {
        operator_id: OPERATOR_ID,
        answers,
      })
      setResult(body)
    } catch (e) {
      setError(e.message)
    }
  }

  return (
    <section aria-label="Quiz" className="space-y-4">
      {lesson.questions.map((q, qi) => (
        <fieldset key={q.question} className="rounded-2xl bg-neutral-900 p-4">
          <legend className="text-xl font-black">
            {qi + 1}. {q.question}
          </legend>
          <div className="mt-3 grid gap-2">
            {q.options.map((opt, oi) => {
              const chosen = answers[qi] === oi
              const verdict = result && chosen ? (result.correct[qi] ? 'right' : 'wrong') : null
              return (
                <button
                  key={opt}
                  type="button"
                  aria-pressed={chosen}
                  disabled={Boolean(result)}
                  onClick={() => setAnswers((a) => a.map((v, i) => (i === qi ? oi : v)))}
                  className={`min-h-14 rounded-xl px-4 text-left text-lg font-bold ${
                    verdict === 'right'
                      ? 'bg-emerald-500 text-black'
                      : verdict === 'wrong'
                        ? 'bg-alert-red'
                        : chosen
                          ? 'bg-cat-yellow text-black'
                          : 'bg-neutral-800'
                  }`}
                >
                  {opt}
                </button>
              )
            })}
          </div>
          {result && <p className="mt-2 text-lg text-neutral-300">{result.explanations[qi]}</p>}
        </fieldset>
      ))}
      {result ? (
        <p role="status" className="text-2xl font-black">
          {result.passed ? 'Passed' : 'Not yet'}: {Math.round(result.score * 100)}%
        </p>
      ) : (
        <button
          onClick={submit}
          disabled={!ready}
          className="min-h-16 w-full rounded-2xl bg-cat-yellow text-2xl font-black text-black disabled:opacity-40"
        >
          Check answers
        </button>
      )}
      {error && <p role="alert">Could not submit: {error}</p>}
    </section>
  )
}

function LessonView({ lessonId, onBack, onPractice }) {
  const { data: lesson } = useJson(`/training/lessons/${lessonId}`)
  const [showGuide, setShowGuide] = useState(false)
  if (!lesson) return <p className="text-xl">Loading lesson…</p>

  return (
    <article aria-label={lesson.title} className="flex flex-col gap-4">
      <button onClick={onBack} className="min-h-12 self-start text-xl font-bold text-cat-yellow">
        ← All lessons
      </button>
      <h2 className="text-3xl font-black">{lesson.title}</h2>
      <ul className="space-y-2 rounded-2xl bg-neutral-900 p-4 text-xl">
        {lesson.key_points.map((p) => (
          <li key={p}>✔ {p}</li>
        ))}
      </ul>
      <div className="flex gap-3">
        <button
          onClick={() => setShowGuide((s) => !s)}
          className="min-h-14 flex-1 rounded-2xl bg-neutral-800 text-xl font-bold"
        >
          {showGuide ? 'Hide guide' : 'Read the guide'}
        </button>
        {lesson.practice && (
          <button
            onClick={() => onPractice(lesson.practice)}
            className="min-h-14 flex-1 rounded-2xl bg-neutral-800 text-xl font-bold"
          >
            Practice this
          </button>
        )}
      </div>
      {showGuide && <Guide guideId={lesson.guide_id} />}
      <Quiz lesson={lesson} />
    </article>
  )
}

/** Curriculum: modules of lessons with progress, each lesson with key points, guide, and quiz. */
export default function LessonsHub({ onPractice = () => {} }) {
  const [refresh, setRefresh] = useState(0)
  const { data: modules, error } = useJson(`/training/modules?operator_id=${OPERATOR_ID}&r=${refresh}`)
  const [lessonId, setLessonId] = useState(null)

  if (lessonId) {
    return (
      <LessonView
        lessonId={lessonId}
        onBack={() => {
          setLessonId(null)
          setRefresh((r) => r + 1)
        }}
        onPractice={onPractice}
      />
    )
  }
  if (error) return <p role="alert">Lessons unavailable: {error}</p>
  if (!modules) return <p className="text-xl">Loading lessons…</p>

  return (
    <section aria-label="Lessons" className="flex flex-col gap-6">
      <CoachCard onOpenLesson={setLessonId} />
      {modules.map((m) => (
        <div key={m.id}>
          <h2 className="mb-3 text-2xl font-black">{m.title}</h2>
          <div className="grid gap-3 md:grid-cols-3">
            {m.lessons.map((l) => (
              <button
                key={l.id}
                onClick={() => setLessonId(l.id)}
                className="min-h-24 rounded-2xl bg-neutral-900 p-4 text-left"
              >
                <span className="block text-xl font-black">{l.title}</span>
                <span className={`text-lg ${l.passed ? 'text-emerald-400' : 'text-neutral-400'}`}>
                  {l.best_score == null
                    ? 'Not started'
                    : `${l.passed ? '✓ Passed' : 'Best'} ${Math.round(l.best_score * 100)}%`}
                </span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </section>
  )
}
