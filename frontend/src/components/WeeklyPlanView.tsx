// A generated weekly plan, day by day. Used by the Dashboard card and the "Your Plan & Basics" page.
import { useState } from 'react'
import { MUSCLE_GROUP_LABELS, type WeeklyProgram } from '../api'
import { useFavorites } from '../favorites'
import { rationaleCredit } from '../injurySafety'
import ExerciseDetail from './ExerciseDetail'
import Link from './Link'
import ReviewInfo from './ReviewInfo'

const DAY_NAMES: Record<string, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}
const SPLITS: Record<string, string> = {
  full_body: 'Full body', circuit: 'Circuit', upper_lower: 'Upper / lower', push_pull_legs: 'Push / pull / legs',
}
const words = (s: string) => s.replace(/_/g, ' ')

export default function WeeklyPlanView({ plan, startOpen = true }: { plan: WeeklyProgram; startOpen?: boolean }) {
  const favorites = useFavorites()
  const [open, setOpen] = useState(startOpen)
  const [openId, setOpenId] = useState<string | null>(null)

  if (!plan.generated) {
    return (
      <div className="clinical-box" role="note">
        <strong>Needs clinical review</strong>
        <p>{plan.blocked_reason}</p>
        <p>
          <Link to="/pregnancy-support">Read the message from our OB-GYN</Link>
        </p>
      </div>
    )
  }
  const p = plan.protocol!

  return (
    <div className="weekly-plan">
      <div className="chip-row">
        <span className="chip">{plan.training_days} days a week</span>
        <span className="chip">{SPLITS[p.split_type] ?? words(p.split_type)}</span>
        <span className="chip">~{p.session_length_minutes} min</span>
        <span className="chip">
          {p.sets_range} sets × {p.reps_range} reps
        </span>
        <span className="chip">{p.rest_seconds}s rest</span>
        {plan.safety?.checked_only && <span className="chip chip-safe">Injury-filtered</span>}
      </div>

      <ol className="week-strip" aria-label="Your week">
        {plan.days.map((d) => (
          <li key={d.day} className={d.kind === 'training' ? 'strip-train' : 'strip-rest'}>
            <span className="strip-day">{DAY_NAMES[d.day].slice(0, 3)}</span>
            <span className="strip-kind">{d.kind === 'training' ? (d.focus ?? 'Train') : 'Rest'}</span>
          </li>
        ))}
      </ol>

      <button type="button" className="btn-ghost" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        {open ? 'Hide the day-by-day plan' : 'Show the day-by-day plan'}
      </button>

      {open && (
        <div className="plan-days">
          {plan.days
            .filter((d) => d.kind === 'training')
            .map((d) => (
              <section key={d.day} className="plan-day">
                <h4>
                  {DAY_NAMES[d.day]} <span className="hint">· {d.focus} · about {Math.round(d.est_minutes)} min</span>
                </h4>
                <ol className="session-list">
                  {d.exercises.map((x, i) => (
                    <li key={x.exercise_id} className={`session-item group-${x.muscle_group}`}>
                      <span className="session-num" aria-hidden="true">
                        {i + 1}
                      </span>
                      <div>
                        <button type="button" className="session-name" onClick={() => setOpenId(x.exercise_id)}>
                          {x.name}
                        </button>
                        <div className="session-meta">
                          <span className="chip chip-small">{MUSCLE_GROUP_LABELS[x.muscle_group]}</span>
                          {x.sets} sets × {x.reps} · rest {x.rest_seconds}s
                        </div>
                        {x.injury_check === 'not_yet_checked' && (
                          <span className="review-tag">Not yet checked for injury safety</span>
                        )}
                      </div>
                    </li>
                  ))}
                </ol>
              </section>
            ))}
          <p className="hint">
            Rest days: {plan.days.filter((d) => d.kind === 'rest').map((d) => DAY_NAMES[d.day]).join(', ')}.
          </p>
        </div>
      )}

      {!!plan.safety?.left_out_for_injury?.length && (
        <details className="left-out">
          <summary>
            Left out for your injury ({plan.safety.left_out_for_injury.length}{' '}
            {plan.safety.left_out_for_injury.length === 1 ? 'exercise' : 'exercises'})
          </summary>
          <ul>
            {plan.safety.left_out_for_injury.map((x) => (
              <li key={x.exercise_id}>
                <button type="button" className="session-name" onClick={() => setOpenId(x.exercise_id)}>
                  {x.name}
                </button>
                {x.cautions.map((c) => (
                  <p key={c.injury}>
                    <strong>{words(c.injury)}:</strong> {c.reasoning ?? 'No reason written yet.'}{' '}
                    {c.tier && c.source && (
                      <span className={c.tier === 'pt_reviewed' ? 'review-tag review-tag-ok' : 'review-tag'}>
                        {rationaleCredit({ tier: c.tier, source: c.source })}
                      </span>
                    )}
                  </p>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}

      <div className="plan-footnotes">
        <ReviewInfo item={p} />
        <details>
          <summary>How we built this</summary>
          <ul>
            <li>Goals: {plan.goals.map(words).join(', ')} ({words(plan.experience_level)})</li>
            {p.blending_rules_applied.length > 0 && (
              <li>Where your goals differ, we used the gentler setting: {p.blending_rules_applied.join('; ')}.</li>
            )}
            {p.progression_notes.map((n) => (
              <li key={n}>Progressing: {n}</li>
            ))}
            {plan.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </details>
      </div>

      {openId && <ExerciseDetail key={openId} exerciseId={openId} favorites={favorites} onClose={() => setOpenId(null)} />}
    </div>
  )
}
