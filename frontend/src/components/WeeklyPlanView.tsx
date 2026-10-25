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
const nice = (s: string) =>
  new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })

function repsText(x: PlanExercise) {
  return x.reps_your_call ? `${x.sets} sets × your call (about ${x.reps})` : `${x.sets} × ${x.reps}`
}

/** The 6 months of the plan as week ranges (weeks 1-26 split into six roughly 4-and-a-bit-week months). */
function months(totalWeeks: number): { label: string; from: number; to: number }[] {
  const out = []
  for (let m = 0; m < 6; m++) {
    const from = Math.floor((m * totalWeeks) / 6) + 1
    const to = Math.floor(((m + 1) * totalWeeks) / 6)
    out.push({ label: `Month ${m + 1}`, from, to })
  }
  return out
}

/** The weights table: suggested weights month by month across the 6-month plan, from the defaults (before anything
 *  is logged). The data has every week; a month shows its range (e.g. 10 to 12.5 lb). */
function WeightTable({ plan }: { plan: WeeklyProgram }) {
  const w = plan.weights
  if (!w) return null
  const cols = months(w.schedule_weeks)
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
                {cols.map((c) => (
                  <th key={c.label} scope="col">
                    {c.label}
                    <span className="hint"> wk {c.from}–{c.to}</span>
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {w.schedule.map((row) => (
                <tr key={row.exercise_id}>
                  <th scope="row">{row.name}</th>
                  {cols.map((c) => {
                    const here = row.weeks.flatMap((wk, i) => (wk >= c.from && wk <= c.to ? [row.weight_lb[i]] : []))
                    if (!here.length) return <td key={c.label}>·</td>
                    const lo = here[0]
                    const hi = here[here.length - 1]
                    return <td key={c.label}>{lo === hi ? lb(lo) : `${lo ?? '?'}–${lb(hi)}`}</td>
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
  // The real day lengths, not the protocol's target: strength days can run shorter than the mobility circuits.
  // Cardio days have no exercises (cardio of your choice), so they aren't counted.
  const minutes = days.filter((d) => d.exercises.length).map((d) => Math.round(d.est_minutes))
  const [shortest, longest] = [Math.min(...minutes), Math.max(...minutes)]

  return (
    <div className="weekly-plan">
      {plan.window && (
        <p className="plan-window">
          {plan.window.ended ? (
            <>
              Your 6-month plan ended {nice(plan.window.ends_on)}. <Link to="/quiz">Retake the quiz</Link> to start a new one.
            </>
          ) : (
            <>
              You're in <strong>week {plan.window.current_week} of {plan.window.weeks}</strong>. Your plan runs from{' '}
              {nice(plan.window.started_on)} to {nice(plan.window.ends_on)}; the {plan.block_weeks}-week pattern below repeats the
              whole way, with the weights going up as you go.
            </>
          )}
        </p>
      )}
      <div className="chip-row">
        <span className="chip">{plan.goal_label}</span>
        <span className="chip">{plan.training_days} days a week</span>
        <span className="chip">6-month plan ({plan.plan_weeks} weeks)</span>
        <span className="chip">pattern repeats every {plan.block_weeks} weeks</span>
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
                  {DAY_NAMES[d.day]}{' '}
                  <span className="hint">
                    · {d.focus}
                    {d.category !== 'cardio' && <> · about {Math.round(d.est_minutes)} min</>}
                  </span>
                </h4>
                {d.category === 'cardio' && (
                  <p className="plan-cardio-note">
                    Walk, run, bike, dance, swim: any cardio you enjoy. Log what you did on your calendar and the day
                    counts as done.
                  </p>
                )}
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
