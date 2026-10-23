// Log cardio: in your own words ("evening walk"), or (when allowed) one of the library's cardio exercises, measured
// however you like: minutes, steps, or distance. A record, not a recommendation: no AI. The calorie range comes from
// code (Compendium MET values x your weight, the Workout Reviewer's method); steps are extra rough, and there's no
// number for "Something else" or while pregnant / postpartum. Your words stay private (never sent to the AI) and get
// the same code-only safety check as notes; a warning sign shows a supportive message, and the log is still saved.
import { useEffect, useState, type FormEvent } from 'react'
import {
  deleteCardio,
  fetchCardioExercises,
  fetchCardioTypes,
  logCardio,
  type CardioEstimate,
  type CardioExercise,
  type CardioLog,
  type CardioMeasure,
  type CardioType,
} from '../api'

let libraryCache: Promise<CardioExercise[]> | null = null
let typesCache: Promise<CardioType[]> | null = null

/** "about 110 to 210 kcal (rough)", linking to the one place with the full caveats. */
export function KcalNote({ estimate, compact = false }: { estimate: CardioEstimate; compact?: boolean }) {
  if (!estimate.available) return compact ? null : <span className="hint">{estimate.reason}</span>
  return (
    <a className="kcal-note" href="#calorie-estimates" title="How we estimate calories">
      ~{estimate.kcal.low}–{estimate.kcal.high} kcal{estimate.rough ? ' (rough)' : ''}
    </a>
  )
}

function amount(l: CardioLog): string {
  if (l.measure === 'steps' && l.steps) return `${l.steps.toLocaleString()} steps`
  if (l.measure === 'distance' && l.distance_miles) return `${l.distance_miles} mi`
  return `${l.duration_minutes} min`
}

export function CardioList({ logs, token, onChange }: { logs: CardioLog[]; token: string; onChange: () => void }) {
  if (!logs.length) return null
  return (
    <ul className="cardio-list">
      {logs.map((l) => (
        <li key={l.id}>
          <span>
            {l.activity ?? l.exercise_name} · {amount(l)} <KcalNote estimate={l.estimate} compact />
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

const MEASURES: { value: CardioMeasure; label: string }[] = [
  { value: 'duration', label: 'Minutes' },
  { value: 'steps', label: 'Steps' },
  { value: 'distance', label: 'Distance' },
]

export default function CardioForm({
  token,
  date,
  allowLibrary,
  onLogged,
  defaultType = '',
  startOpen = false,
  openLabel = '+ Log cardio',
}: {
  token: string
  date: string
  allowLibrary: boolean // false for pregnant / postpartum users: own words only (shared_rules rule 9)
  onLogged: (log: CardioLog) => void
  defaultType?: string
  startOpen?: boolean
  openLabel?: string
}) {
  const [open, setOpen] = useState(startOpen)
  const [activity, setActivity] = useState('')
  const [exerciseId, setExerciseId] = useState('')
  const [cardioType, setCardioType] = useState(defaultType)
  const [measure, setMeasure] = useState<CardioMeasure>('duration')
  const [value, setValue] = useState('20')
  const [unit, setUnit] = useState<'mi' | 'km'>('mi')
  const [library, setLibrary] = useState<CardioExercise[]>([])
  const [types, setTypes] = useState<CardioType[]>([])
  const [message, setMessage] = useState<string | null>(null)
  const [last, setLast] = useState<CardioLog | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (!open) return
    typesCache ??= fetchCardioTypes().catch(() => [])
    typesCache.then(setTypes)
    if (!allowLibrary) return
    libraryCache ??= fetchCardioExercises().catch(() => [])
    libraryCache.then(setLibrary)
  }, [open, allowLibrary])

  // A library pick decides the type (the server does the same), so the measure options follow it.
  const effectiveType = exerciseId ? (library.find((x) => x.id === exerciseId)?.cardio_type ?? 'other') : cardioType
  const type = types.find((t) => t.value === effectiveType)
  const allowed = MEASURES.filter((m) => m.value === 'duration' || (m.value === 'steps' ? type?.steps : type?.distance))
  const usedMeasure = allowed.some((m) => m.value === measure) ? measure : 'duration'

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    setMessage(null)
    try {
      const n = Number(value)
      const r = await logCardio(token, {
        date,
        activity: activity.trim() || undefined,
        exercise_id: exerciseId || undefined,
        cardio_type: exerciseId ? undefined : cardioType || undefined,
        measure: usedMeasure,
        ...(usedMeasure === 'duration' ? { duration_minutes: n } : usedMeasure === 'steps' ? { steps: n } : { distance: n, distance_unit: unit }),
      })
      setActivity('')
      setExerciseId('')
      setLast(r.log)
      if (r.safety.flagged && r.safety.message) setMessage(r.safety.message)
      else setOpen(false)
      onLogged(r.log)
    } catch (err) {
      setError((err as Error).message)
    } finally {
      setBusy(false)
    }
  }

  const logged = last && (
    <p className="success cardio-logged" role="status">
      Logged {last.activity ?? last.exercise_name} ({amount(last)}). <KcalNote estimate={last.estimate} />
    </p>
  )

  if (!open) {
    return (
      <>
        {logged}
        <button type="button" className="btn-ghost btn-small" onClick={() => setOpen(true)}>
          {openLabel}
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
      {logged}
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
      {!exerciseId && (
        <label>
          <span>Kind of cardio</span>
          <select value={cardioType} onChange={(e) => setCardioType(e.target.value)}>
            <option value="">(pick one for a calorie estimate)</option>
            {types.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </label>
      )}
      <fieldset className="cardio-measure">
        <legend>How did you measure it?</legend>
        {allowed.map((m) => (
          <label key={m.value} className="chip-check">
            <input type="radio" name={`measure-${date}`} checked={usedMeasure === m.value} onChange={() => setMeasure(m.value)} />
            {m.label}
          </label>
        ))}
      </fieldset>
      <label>
        <span>{usedMeasure === 'duration' ? 'Minutes' : usedMeasure === 'steps' ? 'Steps' : 'Distance'}</span>
        <span className="number-row">
          <input
            type="number"
            min={usedMeasure === 'distance' ? 0.1 : 1}
            step={usedMeasure === 'distance' ? 0.1 : 1}
            max={usedMeasure === 'duration' ? 600 : usedMeasure === 'steps' ? 100000 : 300}
            value={value}
            onChange={(e) => setValue(e.target.value)}
          />
          {usedMeasure === 'distance' && (
            <select aria-label="Distance unit" value={unit} onChange={(e) => setUnit(e.target.value as 'mi' | 'km')}>
              <option value="mi">miles</option>
              <option value="km">km</option>
            </select>
          )}
        </span>
      </label>
      <div className="day-notes-actions">
        <button type="submit" className="btn-secondary btn-small" disabled={busy || (!activity.trim() && !exerciseId) || !(Number(value) > 0)}>
          {busy ? 'Saving…' : 'Save'}
        </button>
        <button type="button" className="btn-link" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      <p className="hint">Private: never sent to the AI. Calories are a code-computed estimate, never AI.</p>
      {message && (
        <p className="note-support" role="status">
          {message}
        </p>
      )}
      {error && <p className="error">{error}</p>}
    </form>
  )
}
