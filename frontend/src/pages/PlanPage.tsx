// "Your Personalized Plan": your generated weekly plan (GET /api/plan, built by code, no AI). The Workout Basics
// articles used to share this page; they have their own page now (BasicsPage, /basics).
import { useEffect, useState } from 'react'
import { fetchPlan, type WeeklyProgram } from '../api'
import Link from '../components/Link'
import WeeklyPlanView from '../components/WeeklyPlanView'
import { useSession, type Session } from '../session'

function YourPlan({ session }: { session: Session }) {
  const [plan, setPlan] = useState<WeeklyProgram | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchPlan(session.token)
      .then((p) => !cancelled && setPlan(p))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [session.token])

  if (error) {
    return (
      <p className="notice">
        {error} {/quiz/i.test(error) && <Link to="/quiz">Take the quiz</Link>}
      </p>
    )
  }
  if (!plan) return <p className="hint">Loading your plan…</p>
  return (
    <div className="dash-card">
      <WeeklyPlanView plan={plan} />
      <p>
        <Link to="/how-we-build">See how we built this</Link>
      </p>
    </div>
  )
}

export default function PlanPage() {
  const session = useSession()
  return (
    <>
      <h2 className="page-title">Your Personalized Plan</h2>
      <p className="page-sub">
        Your week, built by our own code from your quiz answers. Answers changed? <Link to="/quiz">Retake the quiz</Link>
      </p>
      {session ? (
        <YourPlan key={session.userId} session={session} />
      ) : (
        <p className="notice">
          <Link to="/">Sign in</Link> and take the quiz to see your plan.
        </p>
      )}
    </>
  )
}
