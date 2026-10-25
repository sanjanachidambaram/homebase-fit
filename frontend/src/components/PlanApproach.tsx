// "How your plan works", at the top of the Personalized Plan page (moved from the Dashboard's "Recommended for you"
// card, 2026-10-25): the general approach in plain words, plus the Program Architect's short explanation of YOUR
// plan (POST /api/programs/recommend) on request. The plan itself is built by code; the agent only explains it.
// The explanation is kept for this visit so coming back doesn't spend tokens again.
import { useState } from 'react'
import { recommendProgram, type PlanRecommendation } from '../api'
import { agentError, once } from '../agentCalls'
import Loading from './dashboard/Loading'
import Link from './Link'

const remembered = new Map<number, PlanRecommendation>()

export default function PlanApproach({ token, userId }: { token: string; userId: number }) {
  const [rec, setRec] = useState<PlanRecommendation | null>(() => remembered.get(userId) ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function explain() {
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
    <section className="dash-card plan-approach" aria-labelledby="approach-title">
      <h3 id="approach-title">How your plan works</h3>
      <p>
        Your weeks are built from your quiz: your goal, your experience, your equipment, and any injuries. Our own
        code picks every exercise from the real library, checks it against your injuries first, and sets your sets,
        reps and rest from your goal and level. No AI chooses your workouts. Your goal sets the shape of the week, and
        the pattern repeats so you can see yourself getting stronger.
      </p>

      {!rec && !loading && (
        <button type="button" className="btn" onClick={explain}>
          Explain my plan
        </button>
      )}
      {loading && <Loading text="Reading your plan…" />}
      {error && (
        <p className="error">
          {error} {/quiz/i.test(error) && <Link to="/quiz">Take the quiz</Link>}
        </p>
      )}
      {rec && !loading && (
        <>
          <p className="plan-explanation">{rec.explanation}</p>
          {rec.review_note && <p className="pending-note">{rec.review_note}</p>}
        </>
      )}
      <p>
        <Link to="/how-we-build">See how we build every plan, step by step</Link>
      </p>
    </section>
  )
}
