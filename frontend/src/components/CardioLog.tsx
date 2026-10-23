// Log cardio on a non-strength day: in your own words ("ran 20 min"), or (when allowed) one of the library's cardio
// exercises, plus minutes. A record, not a recommendation: no AI. Your words stay private (never sent to the AI) and
// get the same code-only safety check as notes; a warning sign shows a supportive message, and the log is still saved.
import { useEffect, useState, type FormEvent } from 'react'
import { deleteCardio, fetchCardioExercises, logCardio, type CardioExercise, type CardioLog } from '../api'

let cardioCache: Promise<CardioExercise[]> | null = null

export function CardioList({ logs, token, onChange }: { logs: CardioLog[]; token: string; onChange: () => void }) {
  if (!logs.length) return null
  return (
    <ul className="cardio-list">
      {logs.map((l) => (
        <li key={l.id}>
          <span>
            {l.activity ?? l.exercise_name} · {l.duration_minutes} min
          </span>
          <button
            type="button"
            className="btn-link"
            aria-label={`Delete ${l.activity ?? l.exercise_name}`}
            onClick={() => deleteCardio(token, l.id).then(onChange)}
          >
            remove
          </button>
        </li>
      ))}
    </ul>
  )
}

export default function CardioForm({
  token,
  date,
  allowLibrary,
  onLogged,
}: {
  token: string
  date: string
  allowLibrary: boolean // false for pregnant / postpartum users: own words only (shared_rules rule 9)
  onLogged: () => void
}) {
  const [open, setOpen] = useState(false)
  const [activity, setActivity] = useState('')
  const [exerciseId, setExerciseId] = useState('')
  const [minutes, setMinutes] = useState(20)
  const [library, setLibrary] = useState<CardioExercise[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open || !allowLibrary) return
    cardioCache ??= fetchCardioExercises().catch(() => [])
    cardioCache.then(setLibrary)
  }, [open, allowLibrary])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const r = await logCardio(token, {
        date,
        activity: activity.trim() || undefined,
        exercise_id: exerciseId || undefined,
        duration_minutes: minutes,
      })
      setActivity('')
      setExerciseId('')
      if (r.safety.flagged && r.safety.message) setMessage(r.safety.message)
      else setOpen(false)
      onLogged()
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (!open) {
    return (
      <>
        <button type="button" className="btn-ghost btn-small" onClick={() => setOpen(true)}>
          + Log cardio
        </button>
        {message && (
          <p className="note-support" role="status">
            {message}
          </p>
        )}
      </>
    )
  }
  return (
    <form className="cardio-form" onSubmit={submit}>
      <label>
        <span>What did you do?</span>
        <input
          type="text"
          maxLength={80}
          placeholder="e.g. brisk walk, bike ride"
          value={activity}
          onChange={(e) => setActivity(e.target.value)}
        />
      </label>
      {allowLibrary && (
        <label>
          <span>or pick one</span>
          <select value={exerciseId} onChange={(e) => setExerciseId(e.target.value)}>
            <option value="">(none)</option>
            {library.map((x) => (
              <option key={x.id} value={x.id}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <label>
        <span>Minutes</span>
        <input type="number" min={1} max={600} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
      </label>
      <div className="day-notes-actions">
        <button type="submit" className="btn-secondary btn-small" disabled={busy || (!activity.trim() && !exerciseId)}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="btn-link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      <p className="hint">Private: never sent to the AI.</p>
      {message && (
        <p className="note-support" role="status">
          {message}
        </p>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  )
}
