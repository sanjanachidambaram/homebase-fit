// "Plan for today": today's day from your calendar (GET /api/calendar, the plan laid out on dates). Code only, no
// AI. Logging and ticking it off happen on the Calendar, so this card links there.
import { useEffect, useState } from 'react'
import { fetchCalendar, isSignInGone, MUSCLE_GROUP_LABELS, type CalendarEntry, type CalendarRange } from '../../api'
import { setSession } from '../../session'
import Link from '../Link'
import Loading from './Loading'

const pad = (n: number) => String(n).padStart(2, '0')
/** Today on the person's own clock, as YYYY-MM-DD. */
export function localToday(now = new Date()): string {
  return `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}`
}

function TodayBody({ entry }: { entry: CalendarEntry }) {
  const w = entry.workout
  if (entry.day_type === 'workout') {
    return (
      <>
        <p className="today-focus">
          {w.focus ?? 'Workout'} <span className="hint">· about {Math.round(w.est_minutes)} min</span>
          {entry.completed && <span className="today-done"> · Done ✓</span>}
        </p>
        <ul className="today-list">
          {w.exercises.map((x) => {
            const tip = entry.weights?.[x.exercise_id]
            return (
              <li key={x.exercise_id}>
                <strong>{x.name}</strong>
                <span className="hint">
                  {x.reps_your_call ? `${x.sets} sets × your call` : `${x.sets} × ${x.reps}`} ·{' '}
                  {MUSCLE_GROUP_LABELS[x.muscle_group] ?? x.muscle_group}
                  {tip?.weighted && tip.suggested_lb != null && ` · try ${tip.suggested_lb} lb`}
                </span>
              </li>
            )
          })}
        </ul>
      </>
    )
  }
  if (entry.day_type === 'cardio') {
    return (
      <p className="today-focus">
        {w.focus ?? 'Cardio'}
        {entry.completed ? (
          <span className="today-done"> · Logged ✓</span>
        ) : (
          <span className="hint"> · any cardio you like. Log it on your calendar and the day counts as done.</span>
        )}
      </p>
    )
  }
  return (
    <p className="today-focus">
      {w.open ? 'Open day' : 'Rest day'}
      <span className="hint">
        {' '}
        · {w.open ? 'pick what goes here on your calendar.' : 'rest and recover. Your muscles get stronger on days like this.'}
      </span>
    </p>
  )
}

export default function TodayCard({ token }: { token: string }) {
  const [data, setData] = useState<CalendarRange | null>(null)
  const [error, setError] = useState<string | null>(null)
  const today = localToday()

  useEffect(() => {
    let cancelled = false
    fetchCalendar(token, today, today)
      .then((r) => !cancelled && setData(r))
      .catch((e: Error) => {
        if (cancelled) return
        if (isSignInGone(e)) setSession(null)
        else setError(e.message)
      })
    return () => {
      cancelled = true
    }
  }, [token, today])

  const entry = data?.entries.find((e) => e.date === today)
  return (
    <section className="dash-card today-card" aria-labelledby="today-title">
      <div className="dash-card-head">
        <h3 id="today-title">Plan for today</h3>
      </div>
      {!data && !error && <Loading text="Checking today's plan…" />}
      {error && <p className="error">{error}</p>}
      {data?.needs_quiz && (
        <>
          <p>Take the 2-minute quiz and we'll lay out your plan, starting today.</p>
          <Link to="/quiz" className="btn btn-big">
            Take the quiz
          </Link>
        </>
      )}
      {data && !data.needs_quiz && (entry ? <TodayBody entry={entry} /> : <p>Nothing is on your calendar today.</p>)}
      {data && !data.needs_quiz && (
        <Link to="/calendar" className="btn">
          {entry?.day_type === 'workout' && !entry.completed ? 'Log it on my calendar' : 'Open my calendar'}
        </Link>
      )}
    </section>
  )
}
