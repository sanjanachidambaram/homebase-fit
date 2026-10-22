// "Recommended for you": asks the Program Architect (POST /api/programs/recommend) when the user taps the button.
// The answer is kept for this visit, so coming back to the dashboard doesn't spend tokens again.
import { useState } from 'react'
import { recommendProgram, type ProgramRecommendation } from '../../api'
import { agentError, once } from '../../agentCalls'
import Link from '../Link'
import ReviewInfo from '../ReviewInfo'
import Loading from './Loading'

const DAYS: Record<string, string> = { mon: 'Mon', tue: 'Tue', wed: 'Wed', thu: 'Thu', fri: 'Fri', sat: 'Sat', sun: 'Sun' }
const remembered = new Map<number, ProgramRecommendation>()

export default function ProgramCard({ token, userId }: { token: string; userId: number }) {
  const [rec, setRec] = useState<ProgramRecommendation | null>(() => remembered.get(userId) ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [showPlan, setShowPlan] = useState(false)

  async function ask() {
    setLoading(true)
    setError(null)
    try {
      const r = await once(`program:${userId}`, () => recommendProgram(token))
      remembered.set(userId, r.result)
      setRec(r.result)
    } catch (e) {
      setError(agentError(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="dash-card program-card" aria-labelledby="program-title">
      <div className="dash-card-head">
        <h3 id="program-title">
          <span className="card-icon" aria-hidden="true">🗓️</span> Recommended for you
        </h3>
      </div>

      {!rec && !loading && (
        <>
          <p>We'll match you with a trainer-built program for your goals, leaving out anything that isn't cleared for your injuries.</p>
          <button type="button" className="btn btn-big" onClick={ask}>
            Find my program
          </button>
        </>
      )}
      {loading && <Loading text="Matching you with a program…" />}
      {error && <p className="error">{error}</p>}

      {rec && !loading && rec.recommended && (
        <>
          <h4 className="program-name">{rec.name}</h4>
          <div className="chip-row">
            {rec.matched_goals.map((g) => (
              <span key={g} className="chip">
                {g.replace(/_/g, ' ')}
              </span>
            ))}
          </div>
          <p>{rec.rationale}</p>
          <ReviewInfo item={rec} />
          {rec.review_note && <p className="pending-note">{rec.review_note}</p>}
          {rec.injury_note && <p className="hint">{rec.injury_note}</p>}
          <div className="button-row">
            <button type="button" className="btn" aria-expanded={showPlan} onClick={() => setShowPlan((s) => !s)}>
              {showPlan ? 'Hide the weekly plan' : 'See the weekly plan'}
            </button>
            <button type="button" className="btn-ghost" onClick={ask}>
              Ask again
            </button>
          </div>
          {showPlan && rec.schedule && (
            <div className="week-plan">
              {Object.entries(rec.schedule).map(([day, items]) => (
                <div key={day} className="week-day">
                  <span className="day-dot">{DAYS[day] ?? day}</span>
                  <ul>
                    {items.map((it) => (
                      <li key={it.exercise_id}>
                        {it.name} <span className="hint">· {it.sets} × {it.reps}</span>
                      </li>
                    ))}
                  </ul>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {rec && !loading && !rec.recommended && (
        <>
          <p>{rec.message ?? rec.rationale}</p>
          <div className="button-row">
            {/quiz/i.test(rec.message ?? '') ? (
              <Link to="/quiz" className="btn">
                Take the quiz
              </Link>
            ) : (
              <Link to="/build" className="btn">
                Build your own workout
              </Link>
            )}
            <button type="button" className="btn-ghost" onClick={ask}>
              Ask again
            </button>
          </div>
        </>
      )}
    </section>
  )
}
