// "This week" card: how many workouts you've logged since Monday, and one playful fun fact about them (GET
// /api/progress/this-week; computed by code from your logs, reusing the Coach's comparisons; no AI).
import { useEffect, useState } from 'react'
import { fetchThisWeek, type ThisWeek } from '../../api'
import Link from '../Link'
import Loading from './Loading'

export default function ThisWeekCard({ token }: { token: string }) {
  const [week, setWeek] = useState<ThisWeek | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchThisWeek(token)
      .then((w) => !cancelled && setWeek(w))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [token])

  const n = week?.workouts_logged ?? 0
  return (
    <section className="dash-card week-card" aria-labelledby="week-title">
      <div className="dash-card-head">
        <h3 id="week-title">This week</h3>
      </div>
      {!week && !error && <Loading text="Tallying your week…" />}
      {error && <p className="error">{error}</p>}
      {week && (
        <>
          <p className="week-count">
            <span className="streak-number">{n}</span>
            <span className="streak-unit">
              {n === 1 ? 'workout' : 'workouts'} logged this week
            </span>
          </p>
          {week.fun_fact ? (
            <div className="fun-fact" role="note" aria-label="Fun fact">
              <span className="fun-fact-label">Fun fact</span>
              <span>{week.fun_fact.text}</span>
              <p className="hint fun-fact-basis">
                {week.note} {week.fun_fact.basis}.
              </p>
            </div>
          ) : (
            <p className="hint">
              {week.note} <Link to="/calendar">Go to your calendar</Link>
            </p>
          )}
        </>
      )}
    </section>
  )
}
