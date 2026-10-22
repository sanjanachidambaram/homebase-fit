import AccountForm from '../components/AccountForm'
import { useNeedsClinicalReview } from '../clinicalReview'
import ClinicalSupportCard from '../components/ClinicalSupport'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import { useSession } from '../session'

export default function BuildPage() {
  const session = useSession()
  const clinicalReview = useNeedsClinicalReview(session)
  return (
    <>
      <h2 className="page-title">Build your own workout</h2>
      <p className="page-sub">Pick your muscle groups and your time. We'll do the puzzle.</p>
      {!session ? (
        <>
          <p>Sign in to build a workout around your goals and injuries.</p>
          <AccountForm initialMode="login" />
        </>
      ) : clinicalReview === null ? (
        <p className="hint">Loading…</p>
      ) : clinicalReview ? (
        <ClinicalSupportCard />
      ) : (
        <WorkoutBuilder token={session.token} />
      )}
    </>
  )
}
