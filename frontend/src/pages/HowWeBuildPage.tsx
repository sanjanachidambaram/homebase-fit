// "How We Build Your Plan": the algorithm in plain language, plus a worked example that is a LIVE run of the real
// generator (GET /api/plan/example), never hand-written, so it can't go stale when the rules change.
import { useEffect, useState } from 'react'
import { fetchPlanExample, type PlanExample } from '../api'
import ReviewInfo from '../components/ReviewInfo'
import WeeklyPlanView from '../components/WeeklyPlanView'

const words = (s: string) => s.replace(/_/g, ' ')
const DAY_NAMES: Record<string, string> = {
  mon: 'Monday', tue: 'Tuesday', wed: 'Wednesday', thu: 'Thursday', fri: 'Friday', sat: 'Saturday', sun: 'Sunday',
}

const STEPS = [
  {
    title: 'Your goal sets the shape of your week',
    text: 'Every plan has 4 training days, built from 4 kinds of day: upper body, lower body, mobility and core, and cardio. Getting stronger: 3 strength days (each one upper OR lower body, never mixed) and 1 cardio day, in a 2-week pattern that repeats. Losing weight: 2 strength days and 2 cardio days, in a 4-week pattern. Just feeling good: 2 mobility and core days, 1 strength day and 1 cardio day, in an 8-week pattern. Your goal and experience level pick the sets, reps, rest and session length (15 to 60 minutes). Those are starting values waiting on review by a physical therapist, and they are labeled that way.',
  },
  {
    title: 'If you flagged an injury, keep only exercises checked for it',
    text: 'We drop every exercise tagged as unsafe for your injury, and every exercise nobody has checked for injuries yet. No exceptions. The injury tags themselves are drafts a physical therapist is still reviewing, so always stop anything that hurts.',
  },
  {
    title: 'Keep only what your equipment allows',
    text: "Exercises that need equipment you don't have are removed. Bodyweight moves and a sturdy chair are always assumed.",
  },
  {
    title: 'Fill each day from what’s left, starting with the basics',
    text: 'Each strength day works at least two muscle groups (upper: a push and a pull; lower: a squat-type and a hip-hinge move) plus at least two extra exercises for variety. We reach first for effective, easy-at-home moves (push-ups, rows, squats, glute bridges, planks, marching) from our real library, matched to your experience level, with jumping moves left out of gentle plans. Days change from week to week within the pattern.',
  },
  {
    title: 'Weights start as suggestions and build on what you log',
    text: 'Beginners start with bodyweight only; otherwise we suggest 10 lb (arms) and 20 lb (legs), or 20 and 40 if you’re very experienced. Week 1 is a calibration week: log what you actually did, and later suggestions build on it. Getting stronger adds a little each time a day comes back round; losing weight adds 5 lb every 4 weeks; feeling good leaves your weights where you set them. You can always change any weight.',
  },
]

function Example() {
  const [ex, setEx] = useState<PlanExample | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetchPlanExample()
      .then(setEx)
      .catch((e: Error) => setError(e.message))
  }, [])

  if (error) return <p className="error">Couldn't load the example: {error}</p>
  if (!ex) return <p className="hint">Running the generator…</p>

  const { profile, funnel, plan } = ex
  const p = plan.protocol!
  const top = funnel[0]?.exercises_left || 1
  const rest = plan.days.filter((d) => d.kind === 'rest')

  return (
    <div className="example">
      <p className="example-live">
        Generated live by the same code that builds your plan, every time this page loads. Nothing here is
        written by hand.
      </p>

      <div className="chip-row example-profile">
        <span className="chip">goal: {plan.goal_label}</span>
        <span className="chip">{words(profile.experience_level)}</span>
        <span className="chip">injury: {profile.injury_flags.map(words).join(', ')}</span>
        <span className="chip">equipment: {profile.equipment.map(words).join(', ')}</span>
      </div>

      <section className="example-step">
        <h4>
          <span className="step-num">1</span> The week its goal calls for
        </h4>
        <p>
          <strong>{plan.goal_label}</strong> at the <strong>{words(plan.experience_level)}</strong> level:{' '}
          {plan.training_days} days a week (
          {plan.days.filter((d) => d.kind === 'training').map((d) => d.focus).join(', ')}), a {plan.block_weeks}-week
          pattern, up to {p.session_length_minutes} minutes a day, {p.sets_range} sets of {p.reps_range} reps on strength
          days, {p.rest_seconds} seconds rest.
        </p>
        <ReviewInfo item={p} />
      </section>

      <section className="example-step">
        <h4>
          <span className="step-num">2–3</span> The safety and equipment filters
        </h4>
        <ol className="funnel">
          {funnel.map((s) => (
            <li key={s.step}>
              <div className="funnel-label">
                <span>{s.step}</span>
                <strong>
                  {s.exercises_left.toLocaleString()} left
                  {s.removed > 0 && <span className="funnel-removed"> (−{s.removed.toLocaleString()})</span>}
                </strong>
              </div>
              <div className="funnel-bar" aria-hidden="true">
                <span style={{ width: `${Math.max(1.5, (s.exercises_left / top) * 100)}%` }} />
              </div>
            </li>
          ))}
        </ol>
        <p className="hint">
          Out of {top.toLocaleString()} exercises, {funnel[funnel.length - 1].exercises_left} were left for this person
          to choose from.
        </p>
      </section>

      <section className="example-step">
        <h4>
          <span className="step-num">4–5</span> The weeks it built
        </h4>
        <p>
          {plan.training_days} training days and {rest.length} rest days ({rest.map((d) => DAY_NAMES[d.day]).join(', ')}).
        </p>
        {plan.notes.length > 0 && (
          <ul className="example-notes">
            {plan.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        )}
        <WeeklyPlanView plan={plan} />
      </section>
    </div>
  )
}

export default function HowWeBuildPage() {
  return (
    <div className="how-we-build">
      <h2 className="page-title">How We Build Your Plan</h2>
      <p className="page-sub">
        No AI decides your plan. A fixed set of rules in our code builds it from your quiz answers, and the same
        answers always give the same plan. The AI only writes the short explanation you see afterwards.
      </p>

      <ol className="build-steps">
        {STEPS.map((s, i) => (
          <li key={s.title} className="build-step">
            <span className="step-num" aria-hidden="true">
              {i + 1}
            </span>
            <div>
              <h3>{s.title}</h3>
              <p>{s.text}</p>
            </div>
          </li>
        ))}
      </ol>

      <h3 className="section-title">A worked example</h3>
      <Example />
    </div>
  )
}
