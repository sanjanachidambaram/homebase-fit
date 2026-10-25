// A generated plan: the week structure, each week of the repeating pattern day by day, and how the weights go up.
// Used by the Dashboard card and the "Your Personalized Plan" page. Built by code, never AI.
import { useState } from 'react'
import { MUSCLE_GROUP_LABELS, type PlanExercise, type WeeklyProgram } from '../api'
import { useFavorites } from '../favorites'
import { rationaleCredit } from '../injurySafety'
import ExerciseDetail from './ExerciseDetail'
import Link from './Link'
import ReviewInfo from './ReviewInfo'

const DAY_NAMES: Record<string, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}
const words = (s: string) => s.replace(/_/g, ' ')
const lb = (n: number | null) => (n === null ? 'your pick' : `${n} lb`)

function repsText(x: PlanExercise) {
  return x.reps_your_call ? `${x.sets} sets × your call (about ${x.reps})` : `${x.sets} × ${x.reps}`
}

/** The weights table: suggested starting weights and how they climb, from the defaults (before anything is logged). */
function WeightTable({ plan }: { plan: WeeklyProgram }) {
  const w = plan.weights
  if (!w) return null
  return (
    <section className="progression" aria-label="How the weights go up">
      <h4>How the weights go up</h4>
      <p>{w.rule}</p>
      <p className="hint">{w.calibration}</p>
      {w.schedule.length > 0 ? (
        <div className="weight-table-wrap">
          <table className="weight-table">
            <thead>
              <tr>
                <th scope="col">Exercise</th>
                {Array.from({ length: w.schedule_weeks }, (_, i) => (
                  <th key={i} scope="col">
                    Wk {i + 1}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {w.schedule.map((row) => (
                <tr key={row.exercise_id}>
                  <th scope="row">{row.name}</th>
                  {Array.from({ length: w.schedule_weeks }, (_, i) => {
                    const at = row.weeks.indexOf(i + 1)
                    return <td key={i}>{at === -1 ? '·' : lb(row.weight_lb[at])}</td>
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <p className="hint">This plan's exercises use your bodyweight or bands, so there are no weights to set.</p>
      )}
      <p className="hint">
        {w.defaults_lb
          ? `Starting suggestions for your level: ${w.defaults_lb.arms} lb for arm exercises, ${w.defaults_lb.legs} lb for leg exercises.`
          : 'At your level we start with bodyweight only, so pick your own weights; once you log one, the suggestions build on it.'}{' '}
        Every weight is a suggestion you can change.
      </p>
    </section>
  )
}

export default function WeeklyPlanView({ plan, startOpen = true }: { plan: WeeklyProgram; startOpen?: boolean }) {
  const favorites = useFavorites()
  const [open, setOpen] = useState(startOpen)
  const [week, setWeek] = useState(1)
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
  const days = plan.weeks[week - 1]?.days ?? plan.days
  // The real day lengths, not the protocol's target: strength days can run shorter than the circuits.
  const minutes = days.filter((d) => d.exercises.length).map((d) => Math.round(d.est_minutes))
  const [shortest, longest] = [Math.min(...minutes), Math.max(...minutes)]

  return (
    <div className="weekly-plan">
      <div className="chip-row">
        <span className="chip">{plan.goal_label}</span>
        <span className="chip">{plan.training_days} days a week</span>
        <span className="chip">repeats every {plan.block_weeks} weeks</span>
        {minutes.length > 0 && (
          <span className="chip">
            {shortest === longest ? `about ${shortest}` : `${shortest} to ${longest}`} min a day
          </span>
        )}
        <span className="chip">{p.rest_seconds}s rest between sets</span>
        {plan.safety?.checked_only && <span className="chip chip-safe">Injury-filtered</span>}
      </div>

      {plan.block_weeks > 1 && (
        <div className="week-picker" role="group" aria-label="Week of the pattern">
          {plan.weeks.map((w) => (
            <button
              key={w.week_in_block}
              type="button"
              className="day-choice-btn"
              aria-pressed={week === w.week_in_block}
              onClick={() => setWeek(w.week_in_block)}
            >
              Week {w.week_in_block}
            </button>
          ))}
        </div>
      )}

      <ol className="week-strip" aria-label={`Week ${week}`}>
        {days.map((d) => (
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
          {days
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
                          {repsText(x)} · rest {x.rest_seconds}s
                          {x.weighted && <> · start at {lb(x.default_weight_lb)}</>}
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
            Rest days: {days.filter((d) => d.kind === 'rest').map((d) => DAY_NAMES[d.day]).join(', ')}.
          </p>
        </div>
      )}

      <WeightTable plan={plan} />

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
            <li>
              Goal: {plan.goal_label} ({words(plan.experience_level)}): {p.sets_range} sets of {p.reps_range} reps on
              strength days.
            </li>
            <li>{p.progression_note}</li>
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
