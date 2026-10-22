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
const SPLITS: Record<string, string> = {
  full_body: 'full body', circuit: 'circuit', upper_lower: 'upper / lower', push_pull_legs: 'push / pull / legs',
}

const STEPS = [
  {
    title: 'Match your goals and experience to a training protocol',
    text: 'Each goal (weight loss, strength, tone, rehab, general health) at each experience level has one protocol: how many sessions a week, the split (full body, upper/lower, and so on), and the sets, reps, and rest. Pick more than one goal and we blend them, always taking the gentler setting where they differ. Today these protocols are starting values waiting on review by a physical therapist, and they are labeled that way.',
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
    title: 'Fill each training day from what’s left',
    text: 'Each day gets the muscle groups its split calls for, matched to your experience level, with jumping moves left out of gentle plans. Sets, reps, and rest come straight from the protocol, and each session is sized to your time.',
  },
  {
    title: 'Always keep a rest day',
    text: 'Every week has at least one full rest day, and fewer sessions if you already do other activity on several days.',
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
        <span className="chip">{profile.age} years old</span>
        <span className="chip">{words(profile.experience_level)}</span>
        <span className="chip">goal: {profile.goals.map(words).join(', ')}</span>
        <span className="chip">injury: {profile.injury_flags.map(words).join(', ')}</span>
        <span className="chip">equipment: {profile.equipment.map(words).join(', ')} only</span>
        <span className="chip">{profile.days_available} days free</span>
        <span className="chip">{profile.session_length_minutes}-minute sessions</span>
      </div>

      <section className="example-step">
        <h4>
          <span className="step-num">1</span> The protocol it matched
        </h4>
        <p>
          <strong>{p.goals_used.map(words).join(' + ')}</strong> at the <strong>{words(plan.experience_level)}</strong>{' '}
          level: {p.sessions_per_week} sessions a week, {SPLITS[p.split_type] ?? words(p.split_type)} split, about{' '}
          {p.session_length_minutes} minutes, {p.sets_range} sets of {p.reps_range} reps, {p.rest_seconds} seconds rest.
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
          <span className="step-num">4–5</span> The week it built
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
