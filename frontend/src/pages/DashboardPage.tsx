// Home page. Signed in: the dashboard that ties the agents together. Signed out: the landing page (WelcomePage).
import { useEffect, useState } from 'react'
import { fetchAccount, isSignInGone, type Account } from '../api'
import ClinicalSupportCard from '../components/ClinicalSupport'
import AskBasics from '../components/dashboard/AskBasics'
import CoachCard from '../components/dashboard/CoachCard'
import PlanCard from '../components/dashboard/PlanCard'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import Link from '../components/Link'
import { setSession, useSession, type Session } from '../session'
import WelcomePage from './WelcomePage'

function Dashboard({ session }: { session: Session }) {
  const [account, setAccount] = useState<Account | null>(null)
  const [loadFailed, setLoadFailed] = useState(false)

  useEffect(() => {
    let cancelled = false
    fetchAccount(session.userId, session.token)
      .then((a) => !cancelled && setAccount(a))
      .catch((e: Error) => {
        // Only a bad sign-in (expired, or the account was deleted) signs you out; a server hiccup doesn't.
        if (!cancelled && isSignInGone(e)) setSession(null)
        else if (!cancelled) setLoadFailed(true)
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

      {/* Pregnant / postpartum: no plan, no build-your-own, and no AI cards (all blocked server-side too). */}
      {account?.quiz_profile?.needs_clinical_review ? (
        <ClinicalSupportCard />
      ) : (
        (account || loadFailed) && (
          <>
            <div className="dash-grid">
              <CoachCard token={session.token} userId={session.userId} />
              <PlanCard token={session.token} userId={session.userId} />
              <AskBasics token={session.token} />
            </div>
            <WorkoutBuilder token={session.token} compact />
          </>
        )
      )}
    </div>
  )
}

export default function DashboardPage() {
  const session = useSession()
  return session ? <Dashboard key={session.userId} session={session} /> : <WelcomePage />
}
