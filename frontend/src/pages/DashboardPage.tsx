// Home page. Signed in: the dashboard that ties the four agents together. Signed out: a welcome + sign-up.
import { useEffect, useState } from 'react'
import { fetchAccount, type Account } from '../api'
import AccountForm from '../components/AccountForm'
import AskBasics from '../components/dashboard/AskBasics'
import CoachCard from '../components/dashboard/CoachCard'
import ProgramCard from '../components/dashboard/ProgramCard'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import Link from '../components/Link'
import { setSession, useSession, type Session } from '../session'

function Welcome() {
  return (
    <div className="welcome">
      <section className="hero">
        <h2>
          Home workouts that fit <span className="hl">your</span> body.
        </h2>
        <p>
          Programs and custom sessions for bodyweight and basic home equipment, shaped around your goals and any
          injuries you're working around. Plus a coach who's always in your corner.
        </p>
        <div className="hero-blobs" aria-hidden="true">
          <span />
          <span />
          <span />
        </div>
      </section>
      <AccountForm />
    </div>
  )
}

function Dashboard({ session }: { session: Session }) {
  const [account, setAccount] = useState<Account | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchAccount(session.userId, session.token)
      .then((a) => !cancelled && setAccount(a))
      .catch((e: Error) => {
        // Only a bad sign-in (expired, or the account was deleted) signs you out; a server hiccup doesn't.
        if (!cancelled && /sign in|not found/i.test(e.message)) setSession(null)
      })
    return () => {
      cancelled = true
    }
  }, [session])

  return (
    <div className="dashboard">
      <h2 className="page-title">
        Hey you! <span aria-hidden="true">👋</span>
      </h2>
      <p className="page-sub">Here's your day at a glance.</p>

      {account && !account.quiz_profile && (
        <section className="dash-card quiz-prompt">
          <h3>Start with the 2-minute quiz</h3>
          <p>Tell us your goals and any injuries, and we'll tailor programs and workouts to you.</p>
          <Link to="/quiz" className="btn btn-big">
            Take the quiz
          </Link>
        </section>
      )}

      <div className="dash-grid">
        <CoachCard token={session.token} userId={session.userId} />
        <ProgramCard token={session.token} userId={session.userId} />
        <AskBasics token={session.token} />
      </div>
      <WorkoutBuilder token={session.token} compact />
    </div>
  )
}

export default function DashboardPage() {
  const session = useSession()
  return session ? <Dashboard key={session.userId} session={session} /> : <Welcome />
}
