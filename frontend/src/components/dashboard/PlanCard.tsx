// "Recommended for you": your generated weekly plan (built by code from your quiz) plus the Program Architect's
// short explanation (POST /api/programs/recommend). Kept for this visit so returning doesn't spend tokens again.
import { useState } from 'react'
import { recommendProgram, type PlanRecommendation } from '../../api'
import { agentError, once } from '../../agentCalls'
import Link from '../Link'
import WeeklyPlanView from '../WeeklyPlanView'
import Loading from './Loading'

const remembered = new Map<number, PlanRecommendation>()

export default function PlanCard({ token, userId }: { token: string; userId: number }) {
  const [rec, setRec] = useState<PlanRecommendation | null>(() => remembered.get(userId) ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function build() {
    setLoading(true)
    setError(null)
    try {
      const r = await once(`plan:${userId}`, () => recommendProgram(token))
      remembered.set(userId, r.result)
      setRec(r.result)
    } catch (e) {
      setError(agentError(e))
    } finally {
      setLoading(false)
    }
  }

  return (
    <section className="dash-card program-card" aria-labelledby="plan-title">
      <div className="dash-card-head">
        <h3 id="plan-title">
          Recommended for you
        </h3>
      </div>

      {!rec && !loading && (
        <>
          <p>
            Your week, built from your quiz: your goals, the days and time you have, your equipment, and any injuries,
            with the gentler setting wherever your goals differ.
          </p>
          <button type="button" className="btn btn-big" onClick={build}>
            Build my plan
          </button>
        </>
      )}
      {loading && <Loading text="Building your week…" />}
      {error && (
        <p className="error">
          {error} {/quiz/i.test(error) && <Link to="/quiz">Take the quiz</Link>}
        </p>
      )}

      {rec && !loading && (
        <>
          <p className="plan-explanation">{rec.explanation}</p>
          {rec.review_note && <p className="pending-note">{rec.review_note}</p>}
          <WeeklyPlanView plan={rec.plan} startOpen={false} />
          <div className="button-row">
            <Link to="/plan" className="btn">
              Open my full plan
            </Link>
            <Link to="/how-we-build" className="btn-ghost">
              See how we built this
            </Link>
          </div>
        </>
      )}
    </section>
  )
}
