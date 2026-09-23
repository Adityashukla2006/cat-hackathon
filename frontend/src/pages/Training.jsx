import SimTaskRunner from '../components/SimTaskRunner'

export default function Training() {
  return (
    <main className="mx-auto flex max-w-4xl flex-col gap-4 p-4">
      <h1 className="text-3xl font-black">Training</h1>
      <h2 className="text-2xl font-bold">Joystick simulator</h2>
      <p className="text-lg text-neutral-300">
        ISO pattern. Left stick: stick in/out and swing. Right stick: boom up/down and bucket.
      </p>
      <SimTaskRunner />
    </main>
  )
}
