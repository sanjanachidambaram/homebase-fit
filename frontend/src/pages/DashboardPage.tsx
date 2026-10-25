// Home page. Signed in: the Dashboard, which shows only two things (2026-10-25): the plan for today, then your
// streak. Both are computed by code, no AI. The plan's explanation lives on the Personalized Plan page.
// Signed out: the landing page (WelcomePage).
import { useEffect, useState } from 'react'
import { fetchAccount, isSignInGone, type Account } from '../api'
import ClinicalSupportCard from '../components/ClinicalSupport'
import StreakCard from '../components/dashboard/StreakCard'
import TodayCard from '../components/dashboard/TodayCard'
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

  // The first name is only for this greeting; it never leaves the app (no agent sees it). Accounts made before
  // names were asked for have none. Blank until the account loads, so "Hi there" doesn't flash before the name.
  const greeting = account?.first_name ? `Hi ${account.first_name}` : 'Hi there'
  const ready = account || loadFailed

  return (
    <div className="dashboard">
      <h2 className="page-title">{ready ? greeting : ' '}</h2>
      {ready && (
        <div className="dash-stack">
          {/* Pregnant / postpartum: no plan, so the support card stands in for today's plan (blocked server-side too). */}
          {account?.quiz_profile?.needs_clinical_review ? (
            <ClinicalSupportCard />
          ) : (
            <TodayCard token={session.token} />
          )}
          <StreakCard token={session.token} />
        </div>
      )}
    </div>
  )
}

export default function DashboardPage() {
  const session = useSession()
  return session ? <Dashboard key={session.userId} session={session} /> : <WelcomePage />
}
