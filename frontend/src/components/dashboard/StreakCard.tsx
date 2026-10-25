// Streak card: current and longest streak, active days in the last 30, and day-streak badges (GET
// /api/progress/streak, computed by code from your logged workouts; no AI).
import { useEffect, useState } from 'react'
import { fetchStreak, type StreakStats } from '../../api'
import BeeLogo from '../BeeLogo'
import Loading from './Loading'

const days = (n: number) => `${n} day${n === 1 ? '' : 's'}`

export default function StreakCard({ token }: { token: string }) {
  const [stats, setStats] = useState<StreakStats | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    let cancelled = false
    fetchStreak(token)
      .then((s) => !cancelled && setStats(s))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [token])

  return (
    <section className="dash-card streak-card" aria-labelledby="streak-title">
      <div className="dash-card-head">
        <h3 id="streak-title">Your streak</h3>
      </div>
      {!stats && !error && <Loading text="Counting your days…" />}
      {error && <p className="error">{error}</p>}
      {stats?.found && (
        <>
          <div className="streak-hero">
            <BeeLogo size={56} />
            <p>
              <span className="streak-number">{stats.current_streak_days}</span>
              <span className="streak-unit">{stats.current_streak_days === 1 ? 'day' : 'days'} in a row</span>
            </p>
          </div>
          <dl className="stat-row">
            <div>
              <dt>Longest streak</dt>
              <dd>{days(stats.longest_streak_days)}</dd>
            </div>
            <div>
              <dt>Active days (last 30)</dt>
              <dd>{stats.active_days_last_30}</dd>
            </div>
          </dl>
          <ul className="streak-badges" aria-label="Streak badges">
            {stats.badges.map((b) => (
              <li key={b.days} className={b.earned ? 'badge-earned' : 'badge-locked'}>
                <span aria-hidden="true">{b.earned ? '★' : '☆'}</span> {days(b.days)}
                <span className="sr-only">{b.earned ? ', earned' : ', not earned yet'}</span>
              </li>
            ))}
          </ul>
          {stats.next_badge && (
            <p className="hint">
              {days(stats.next_badge.to_go)} to go until your {days(stats.next_badge.days)} badge.
            </p>
          )}
          {stats.rest_day_suggested && (
            <div className="rest-note" role="note">
              <strong>Rest day, recommended</strong>
              <p>That's a long run of days in a row. A rest day helps your muscles recover, and the streak will wait.</p>
            </div>
          )}
          <p className="hint">
            A streak counts days in a row with a logged workout or cardio, ending today (or yesterday, if you haven't
            logged anything yet today).
          </p>
        </>
      )}
    </section>
  )
}
