import AccountForm from '../components/AccountForm'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import { useSession } from '../session'

export default function BuildPage() {
  const session = useSession()
  return (
    <>
      <h2 className="page-title">Build your own workout</h2>
      <p className="page-sub">Pick your muscle groups and your time. We'll do the puzzle.</p>
      {session ? (
        <WorkoutBuilder token={session.token} />
      ) : (
        <>
          <p>Sign in to build a workout around your goals and injuries.</p>
          <AccountForm initialMode="login" />
        </>
      )}
    </>
  )
}
