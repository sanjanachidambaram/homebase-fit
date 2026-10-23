// "Build your own workout": muscle-group picks + time budget -> POST /api/workouts/build (Workout Builder agent).
// The calendar reuses it for "Build your own for this day" by passing `build` (POST /api/calendar/{id}/custom):
// same form, same agent, same injury filter.
import { useId, useState, type FormEvent } from 'react'
import {
  buildWorkout,
  MUSCLE_GROUP_LABELS,
  reviewWorkout,
  type MuscleGroup,
  type WorkoutRequest,
  type WorkoutSession,
} from '../../api'
import { agentError } from '../../agentCalls'
import { useEquipmentOptions } from '../../equipment'
import { useFavorites } from '../../favorites'
import ExerciseDetail from '../ExerciseDetail'
import ReviewWorkout from '../WorkoutReview'
import SaveToCalendar from '../SaveToCalendar'
import Loading from './Loading'

const MAX_PER_GROUP = 6
const MAX_TOTAL = 12
const GROUPS = Object.keys(MUSCLE_GROUP_LABELS) as MuscleGroup[]

export default function WorkoutBuilder({
  token,
  compact = false,
  title = 'Build your own workout',
  submitLabel = 'Build my workout',
  build,
  onBuilt,
}: {
  token: string
  compact?: boolean
  title?: string
  submitLabel?: string
  /** Where the request goes; defaults to POST /api/workouts/build. */
  build?: (req: WorkoutRequest) => Promise<WorkoutSession>
  onBuilt?: (session: WorkoutSession) => void
}) {
  const favorites = useFavorites()
  const titleId = useId()
  const [picks, setPicks] = useState<Record<MuscleGroup, number>>(
    // Every muscle group starts at 0 (legs and core used to start at 2, a leftover sample default).
    () => Object.fromEntries(GROUPS.map((g) => [g, 0])) as Record<MuscleGroup, number>,
  )
  const [minutes, setMinutes] = useState(10) // the session-time slider starts at its 10-minute minimum
  const [equipment, setEquipment] = useState<string[]>([])
  // The equipment chips come from the exercises themselves (GET /api/exercises/equipment), never a typed list.
  const equipmentOptions = useEquipmentOptions()
  const [session, setSession] = useState<WorkoutSession | null>(null)
  const [builtId, setBuiltId] = useState<number | null>(null) // the server's copy of this session ("Save to calendar")
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)

  const total = Object.values(picks).reduce((a, b) => a + b, 0)
  const change = (g: MuscleGroup, delta: number) =>
    setPicks((p) => {
      const next = Math.max(0, Math.min(MAX_PER_GROUP, p[g] + delta))
      if (delta > 0 && total >= MAX_TOTAL) return p
      return { ...p, [g]: next }
    })

  async function submit(e: FormEvent) {
    e.preventDefault()
    if (total === 0) {
      setError('Pick at least one exercise.')
      return
    }
    setLoading(true)
    setError(null)
    try {
      const chosen = Object.fromEntries(Object.entries(picks).filter(([, n]) => n > 0))
      const req = { picks: chosen, time_budget_minutes: minutes, equipment }
      let result: WorkoutSession
      if (build) {
        result = await build(req)
        setBuiltId(null)
      } else {
        const r = await buildWorkout(token, req)
        result = r.result
        setBuiltId(r.built_id)
      }
      setSession(result)
      onBuilt?.(result)
    } catch (err) {
      setError(agentError(err))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className={`dash-card builder-card${compact ? '' : ' builder-full'}`} aria-labelledby={titleId}>
      <div className="dash-card-head">
        <h3 id={titleId}>
          {title}
        </h3>
      </div>

      <form onSubmit={submit} className="builder-form">
        <fieldset className="builder-picks">
          <legend>
            How many moves per muscle group? <span className="hint">({total} of {MAX_TOTAL} max)</span>
          </legend>
          {GROUPS.map((g) => (
            <div key={g} className={`stepper group-${g}`}>
              <span className="stepper-label">{MUSCLE_GROUP_LABELS[g]}</span>
              <button type="button" aria-label={`Fewer ${MUSCLE_GROUP_LABELS[g]}`} onClick={() => change(g, -1)} disabled={picks[g] === 0}>
                −
              </button>
              <output aria-live="polite">{picks[g]}</output>
              <button
                type="button"
                aria-label={`More ${MUSCLE_GROUP_LABELS[g]}`}
                onClick={() => change(g, 1)}
                disabled={picks[g] === MAX_PER_GROUP || total >= MAX_TOTAL}
              >
                +
              </button>
            </div>
          ))}
        </fieldset>

        <div className="builder-side">
          <label className="range-field">
            <span>
              Time you have: <strong>{minutes} minutes</strong>
            </span>
            <input type="range" min={10} max={60} step={5} value={minutes} onChange={(e) => setMinutes(Number(e.target.value))} />
          </label>

          <fieldset className="equipment">
            <legend>What do you have at home?</legend>
            {equipmentOptions === null && <p className="hint">Loading equipment…</p>}
            {equipmentOptions?.length === 0 && <p className="hint">Couldn't load the equipment list. Try reloading.</p>}
            <div className="chip-row" data-testid="equipment-picker">
              {equipmentOptions?.map((eq) =>
                eq.always_included ? (
                  <label key={eq.value} className="chip-check chip-on chip-locked" title="Bodyweight moves are always included">
                    <input type="checkbox" checked disabled value={eq.value} />
                    {eq.label} (always)
                  </label>
                ) : (
                  <label key={eq.value} className={`chip-check${equipment.includes(eq.value) ? ' chip-on' : ''}`}>
                    <input
                      type="checkbox"
                      value={eq.value}
                      checked={equipment.includes(eq.value)}
                      onChange={(e) =>
                        setEquipment((cur) => (e.target.checked ? [...cur, eq.value] : cur.filter((x) => x !== eq.value)))
                      }
                    />
                    {eq.label}
                  </label>
                ),
              )}
            </div>
            <p className="hint">Bodyweight moves are always included. The list is every piece of equipment our exercises use.</p>
          </fieldset>

          <button type="submit" className="btn btn-big" disabled={loading || total === 0}>
            {loading ? 'Building…' : submitLabel}
          </button>
        </div>
      </form>

      {loading && <Loading text="Picking moves that fit your time and your body…" />}
      {error && <p className="error">{error}</p>}

      {session && !loading && (
        <div className="session">
          <div className="session-summary">
            <strong>
              {session.exercises.length} moves · about {Math.round(session.total_estimated_minutes)} of {session.time_budget_minutes} minutes
            </strong>
            <div className="time-bar" aria-hidden="true">
              <span style={{ width: `${Math.min(100, (session.total_estimated_minutes / session.time_budget_minutes) * 100)}%` }} />
            </div>
          </div>
          <ol className="session-list">
            {session.exercises.map((x) => (
              <li key={x.exercise_id} className={`session-item group-${x.muscle_group}`}>
                <span className="session-num" aria-hidden="true">
                  {x.order}
                </span>
                <div>
                  <button type="button" className="session-name" onClick={() => setOpenId(x.exercise_id)}>
                    {x.name}
                  </button>
                  <div className="session-meta">
                    <span className="chip chip-small">{MUSCLE_GROUP_LABELS[x.muscle_group]}</span>
                    {x.sets} × {x.reps} · rest {x.rest_seconds}s · ~{x.est_minutes} min
                  </div>
                  {x.injury_check === 'not_yet_checked' && (
                    <span className="review-tag">Not yet checked for injury safety</span>
                  )}
                </div>
              </li>
            ))}
          </ol>
          <p className="balance-note">
            <strong>Balance:</strong> {session.balance_note}
          </p>
          {session.notes.map((n) => (
            <p key={n} className="hint">
              {n}
            </p>
          ))}
          {/* key: a new session gets a fresh review button */}
          <ReviewWorkout
            key={session.exercises.map((x) => x.exercise_id).join(',')}
            load={() =>
              reviewWorkout(
                token,
                session.exercises.map(({ exercise_id, sets, reps, rest_seconds }) => ({ exercise_id, sets, reps, rest_seconds })),
              )
            }
          />
          {/* Standalone Build Your Own page only (the calendar's own builder already saves to its day). */}
          {!build && builtId !== null && session.exercises.length > 0 && (
            <SaveToCalendar key={builtId} token={token} builtId={builtId} />
          )}
        </div>
      )}

      {openId && <ExerciseDetail key={openId} exerciseId={openId} favorites={favorites} onClose={() => setOpenId(null)} />}
    </section>
  )
}
