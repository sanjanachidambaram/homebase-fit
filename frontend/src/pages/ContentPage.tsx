// "Your Plan & Basics": your generated weekly plan (GET /api/plan, built by code, no AI) and the Fitness Basics articles.
import { useEffect, useState } from 'react'
import { fetchArticles, fetchPlan, type Article, type WeeklyProgram } from '../api'
import Link from '../components/Link'
import ReviewInfo from '../components/ReviewInfo'
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

export default function ContentPage() {
  const session = useSession()
  const [articles, setArticles] = useState<Article[]>([])
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchArticles()
      .then(setArticles)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <>
      <h2 className="page-title">Your Plan &amp; Basics</h2>

      <h3 className="section-title">Your weekly plan</h3>
      {session ? (
        <YourPlan key={session.userId} session={session} />
      ) : (
        <p className="notice">
          <Link to="/">Sign in</Link> and take the quiz to see your plan.
        </p>
      )}

      <h3 className="section-title">Fitness Basics</h3>
      {error && <p className="error">Couldn't load content: {error}</p>}
      <div className="content-list">
        {articles.map((a) => (
          <article key={a.slug} className="content-item">
            <h4>{a.title}</h4>
            <p className="meta">Category: {a.category.replace(/_/g, ' ')}</p>
            <ReviewInfo item={a} />
          </article>
        ))}
      </div>
    </>
  )
}
