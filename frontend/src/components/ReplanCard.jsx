/** Shows the Dispatcher's new task order with its one-line reason. */
export default function ReplanCard({ replan, tasks, currentSeq, onDismiss }) {
  if (!replan) return null
  const bySeq = Object.fromEntries((tasks ?? []).map((t) => [t.seq, t]))
  const cut = replan.new_order.indexOf(currentSeq)
  const upcoming = cut >= 0 ? replan.new_order.slice(cut + 1) : replan.new_order

  return (
    <section aria-label="New plan" className="rounded-2xl border-4 border-cat-yellow bg-neutral-900 p-5">
      <p className="text-2xl font-black text-cat-yellow">New plan</p>
      <p className="mt-1 text-xl">{replan.explanation}</p>
      <ol className="mt-3 space-y-1 text-xl font-bold">
        {upcoming.map((seq, i) => (
          <li key={seq}>
            {i + 1}. {bySeq[seq]?.description ?? `Task ${seq}`}
          </li>
        ))}
      </ol>
      <button
        onClick={onDismiss}
        className="mt-4 min-h-16 w-full rounded-2xl bg-cat-yellow text-2xl font-black text-black"
      >
        OK
      </button>
    </section>
  )
}
