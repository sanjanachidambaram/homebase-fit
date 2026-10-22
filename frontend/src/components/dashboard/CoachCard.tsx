// Coach widget: calls GET /api/coach/summary when the dashboard loads.
import { useEffect, useState } from 'react'
import { fetchCoach, type CoachMessage, type GoalStatus } from '../../api'
import { agentError, once } from '../../agentCalls'
import Confetti from './Confetti'
import Loading from './Loading'

const STATUS: Record<GoalStatus, { label: string; className: string }> = {
  ahead: { label: 'Ahead of plan', className: 'goal-ahead' },
  on_track: { label: 'On track', className: 'goal-on-track' },
  behind: { label: 'A little behind, and every session counts', className: 'goal-behind' },
  insufficient_data: { label: 'Too early to tell', className: 'goal-early' },
}

export default function CoachCard({ token, userId }: { token: string; userId: number }) {
  const [round, setRound] = useState(0)
  const [result, setResult] = useState<{ round: number; data?: CoachMessage; error?: string } | null>(null)

  useEffect(() => {
    let cancelled = false
    once(`coach:${userId}:${round}`, () => fetchCoach(token))
      .then((r) => !cancelled && setResult({ round, data: r.result }))
      .catch((e) => !cancelled && setResult({ round, error: agentError(e) }))
    return () => {
      cancelled = true
    }
  }, [token, userId, round])

  const current = result?.round === round ? result : null
  const coach = current?.data
  const celebrate = coach && (coach.goal_status === 'on_track' || coach.goal_status === 'ahead')

  return (
    <section className="dash-card coach-card" aria-labelledby="coach-title">
      {celebrate && <Confetti />}
      <div className="dash-card-head">
        <h3 id="coach-title">
          <span className="card-icon" aria-hidden="true">✨</span> Your coach
        </h3>
        {coach && (
          <button type="button" className="btn-ghost" onClick={() => setRound((n) => n + 1)}>
            New message
          </button>
        )}
      </div>

      {!current && <Loading text="Your coach is lacing up…" />}
      {current?.error && <p className="error">{current.error}</p>}

      {coach && (
        <>
          <p className="coach-text">{coach.encouragement}</p>
          <div className="coach-row">
            <span className={`goal-badge ${STATUS[coach.goal_status].className}${celebrate ? ' goal-celebrate' : ''}`}>
              {celebrate && <span aria-hidden="true">🎉 </span>}
              Goal: {STATUS[coach.goal_status].label}
            </span>
          </div>
          {coach.fun_fact && (
            <p className="fun-fact">
              <span className="fun-fact-label">Fun fact</span> {coach.fun_fact}
            </p>
          )}
          <dl className="stat-row">
            <div>
              <dt>Day streak</dt>
              <dd>{coach.current_streak_days}</dd>
            </div>
            <div>
              <dt>Workouts (30 days)</dt>
              <dd>{coach.sessions_last_30_days}</dd>
            </div>
            <div>
              <dt>Pounds lifted</dt>
              <dd>{coach.total_weight_lifted_lbs.toLocaleString()}</dd>
            </div>
          </dl>
          {coach.overtraining_flag && coach.rest_suggestion && (
            <div className="rest-note" role="note">
              <strong>
                <span aria-hidden="true">💜 </span>Rest day, recommended
              </strong>
              <p>{coach.rest_suggestion}</p>
            </div>
          )}
        </>
      )}
    </section>
  )
}
