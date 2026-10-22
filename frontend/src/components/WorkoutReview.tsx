// "Review this workout": muscle coverage, push/pull balance and a caveated estimate range, all computed by the
// server's code (app/services/workout_review.py). The AI only writes the short summary, and the server swaps in
// a plain one if the AI uses any number the code didn't compute. Every estimate is a range, never one number.
import { useState } from 'react'
import { MUSCLE_GROUP_LABELS, type WorkoutReview } from '../api'
import { agentError } from '../agentCalls'
import Loading from './dashboard/Loading'

const n = (x: number) => x.toLocaleString()

export function ReviewPanel({ review }: { review: WorkoutReview }) {
  const { coverage: c, estimate: e } = review
  return (
    <div className="review-panel">
      <p className="review-summary">{review.summary}</p>
      <p className="hint">
        {review.summary_by === 'model'
          ? 'Summary written by our AI from the numbers below; it isn’t allowed to use any other numbers.'
          : 'Summary written from the numbers below.'}
      </p>

      <h4>Muscle coverage</h4>
      <div className="chip-row">
        {c.groups_hit.map((g) => (
          <span key={g.group} className="chip chip-small chip-hit">
            ✓ {MUSCLE_GROUP_LABELS[g.group]} ({g.exercises})
          </span>
        ))}
        {c.groups_missing.map((g) => (
          <span key={g} className="chip chip-small chip-missing">
            {MUSCLE_GROUP_LABELS[g]}: not included
          </span>
        ))}
      </div>
      <p>
        <strong>Push / pull:</strong> {c.upper_body_balance.note}
      </p>
      {c.notes.map((note) => (
        <p key={note} className="hint">
          {note}
        </p>
      ))}

      <h4>Rough estimate</h4>
      {!e.available ? (
        <p className="hint">{e.reason}</p>
      ) : (
        <>
          <dl className="estimate-list">
            <dt>Energy per session (about {e.session_minutes} min)</dt>
            <dd>
              roughly {n(e.per_session_kcal.low)} to {n(e.per_session_kcal.high)} calories
            </dd>
            {e.weekly_kcal && (
              <>
                <dt>If you did this on each of your {e.sessions_per_week} training days a week</dt>
                <dd>
                  roughly {n(e.weekly_kcal.low)} to {n(e.weekly_kcal.high)} calories a week
                </dd>
              </>
            )}
            {e.weight_change && (
              <>
                <dt>Over {e.weight_change.weeks} weeks, from the workouts alone</dt>
                <dd>
                  roughly {e.weight_change.pounds.low} to {e.weight_change.pounds.high} pounds
                  <span className="estimate-label">{e.weight_change.label}</span>
                </dd>
              </>
            )}
          </dl>
          <ul className="caveat-list">
            {e.caveats.map((cv) => (
              <li key={cv}>{cv}</li>
            ))}
            {e.weight_change && <li>{e.weight_change.cdc_context}</li>}
          </ul>
          <details className="method">
            <summary>How we calculated this</summary>
            <p>
              {e.method.formula}. Low end: MET {e.method.low.met} (Compendium code {e.method.low.code},{' '}
              {e.method.low.activity.toLowerCase()}). High end: MET {e.method.high.met} (code {e.method.high.code},{' '}
              {e.method.high.activity.toLowerCase()}).
            </p>
          </details>
        </>
      )}

      {review.citations.length > 0 && (
        <p className="review-sources">
          Sources:{' '}
          {review.citations.map((s, i) => (
            <span key={s.id}>
              {i > 0 && ' · '}
              {s.url ? (
                <a href={s.url} target="_blank" rel="noopener noreferrer">
                  {s.name}
                </a>
              ) : (
                s.name
              )}
            </span>
          ))}
        </p>
      )}
    </div>
  )
}

/** A "Review this workout" button that loads and shows the review. `load` decides which endpoint is used. */
export default function ReviewWorkout({ load }: { load: () => Promise<{ result: WorkoutReview }> }) {
  const [review, setReview] = useState<WorkoutReview | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function run() {
    setBusy(true)
    setError(null)
    try {
      setReview((await load()).result)
    } catch (e) {
      setError(agentError(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="workout-review" aria-label="Workout review">
      {!review && !busy && (
        <button type="button" className="btn-secondary" onClick={run}>
          Review this workout
        </button>
      )}
      {busy && <Loading text="Checking coverage and running the numbers…" />}
      {error && <p className="error">{error}</p>}
      {review && <ReviewPanel review={review} />}
    </section>
  )
}
