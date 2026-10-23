// Build Your Own: build a strength session with the Workout Builder (and save it to a calendar day), or log cardio you
// did. Cardio lives here too: pick the day, what you did, and minutes, steps or distance; the calorie range is code
// (never AI), and logging onto a rest, open or cardio day on your calendar marks that day done.
import { useState } from 'react'
import AccountForm from '../components/AccountForm'
import CardioForm from '../components/CardioLog'
import { useNeedsClinicalReview } from '../clinicalReview'
import ClinicalSupportCard from '../components/ClinicalSupport'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import Link from '../components/Link'
import { useSession } from '../session'

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

function LogCardio({ token, allowLibrary }: { token: string; allowLibrary: boolean }) {
  const [today] = useState(() => iso(new Date()))
  const [date, setDate] = useState(today)
  return (
    <section className="dash-card build-cardio" aria-labelledby="build-cardio-title">
      <h3 id="build-cardio-title">Log cardio</h3>
      <p className="hint">
        Walked, ran, rode, swam? Log it here or on your <Link to="/calendar">calendar</Link>. It counts toward your
        streak, and a rest or cardio day on your calendar is marked done.
      </p>
      <label className="build-cardio-date">
        <span>Day</span>
        <input type="date" value={date} max={today} onChange={(e) => setDate(e.target.value || today)} />
      </label>
      <CardioForm
        key={date}
        token={token}
        date={date}
        allowLibrary={allowLibrary}
        startOpen
        openLabel="+ Log more cardio"
        onLogged={() => undefined} // the form shows what was logged and its estimate
      />
    </section>
  )
}

export default function BuildPage() {
  const session = useSession()
  const clinicalReview = useNeedsClinicalReview(session)
  return (
    <>
      <h2 className="page-title">Build your own workout</h2>
      <p className="page-sub">Pick your muscle groups and your time. We'll do the puzzle. Or log some cardio.</p>
      {!session ? (
        <>
          <p>Sign in to build a workout around your goals and injuries.</p>
          <AccountForm initialMode="login" />
        </>
      ) : clinicalReview === null ? (
        <p className="hint">Loading…</p>
      ) : clinicalReview ? (
        <>
          <ClinicalSupportCard />
          {/* Their own activity log still works (shared_rules rule 9): own words only, no calorie numbers. */}
          <LogCardio token={session.token} allowLibrary={false} />
        </>
      ) : (
        <>
          <WorkoutBuilder token={session.token} />
          <LogCardio token={session.token} allowLibrary />
        </>
      )}
    </>
  )
}
