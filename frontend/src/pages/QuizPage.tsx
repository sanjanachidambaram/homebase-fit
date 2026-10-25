// Onboarding quiz: account -> a word from Summer (an optional, skippable audio message) -> general questions (goal,
// experience, equipment) -> REQUIRED medical disclaimer acknowledgment -> health questions (injuries, pregnancy;
// weight and goal weight only if the goal is losing weight) -> review your answers -> submit.
// Health questions (health: true in quiz_questions.yaml) stay hidden until the disclaimer is accepted, and the API
// rejects any submission without consent. Questions with ask_if are only shown (and only sent) when that answer
// matches; the API ignores them otherwise too.
import { useEffect, useLayoutEffect, useState } from 'react'
import { fetchQuizQuestions, isSignInGone, submitQuiz, type QuizProfile, type QuizQuestion } from '../api'
import AccountForm from '../components/AccountForm'
import CalendarModeChooser from '../components/CalendarModeChooser'
import { ConsentStep } from '../components/Legal'
import { CONSENT_VERSION } from '../legal'
import Link from '../components/Link'
import { navigate } from '../router'
import { setSession, useSession } from '../session'
import QuestionField, { type Answer } from '../components/QuestionField'
import SummerIntro from '../components/SummerIntro'

type Step = 'intro' | 'general' | 'consent' | 'health' | 'review' | 'done'

function isAnswered(q: QuizQuestion, value: Answer | undefined): boolean {
  if (q.type === 'multi_select') return Array.isArray(value) && value.length > 0
  if (q.type === 'number') return typeof value === 'number' && Number.isFinite(value)
  return value !== undefined && value !== ''
}

function rangeError(q: QuizQuestion, value: Answer | undefined): string | null {
  if (q.type !== 'number' || typeof value !== 'number') return null
  if ((q.min !== undefined && value < q.min) || (q.max !== undefined && value > q.max)) {
    return `"${q.prompt}" must be between ${q.min} and ${q.max}.`
  }
  return null
}

/** Is this question asked, given the answers so far? (ask_if: e.g. weight only when the goal is losing weight) */
const asked = (q: QuizQuestion, answers: Record<string, Answer>) =>
  !q.ask_if || answers[q.ask_if.question] === q.ask_if.equals

/** A gentle, cited note (never a block): roughly how long the change takes at a gradual 1-2 lb a week. */
function PaceNote({ q, answers }: { q: QuizQuestion; answers: Record<string, Answer> }) {
  const note = q.pace_note
  const { weight, goal_weight: goal } = answers
  if (!note || typeof weight !== 'number' || typeof goal !== 'number' || !(weight > goal)) return null
  const [slow, fast] = note.lbs_per_week
  const change = weight - goal
  const [label, url] = note.source.split(/:\s(?=https?:)/)
  return (
    <div className="pace-note" role="note">
      <p>
        <strong>
          That's {change} lb: at a gradual {slow} to {fast} lb a week, roughly {Math.ceil(change / fast)} to{' '}
          {Math.ceil(change / slow)} weeks.
        </strong>{' '}
        {note.text} There's no deadline; go at whatever pace works for you.
      </p>
      <p className="hint">
        Source:{' '}
        {url ? (
          <a href={url} target="_blank" rel="noopener noreferrer">
            {label}
          </a>
        ) : (
          note.source
        )}
      </p>
    </div>
  )
}

/** The answer as the person would read it: option labels, not stored values. */
function shown(q: QuizQuestion, value: Answer | undefined): string {
  if (value === undefined || value === '' || (Array.isArray(value) && !value.length)) return 'Not answered'
  const label = (v: string) => q.options.find((o) => o.value === v)?.label ?? v
  if (Array.isArray(value)) {
    const all = q.always_included && !value.includes(q.always_included) ? [q.always_included, ...value] : value
    return all.map(label).join(', ')
  }
  if (q.type === 'single_select') return label(String(value))
  return `${value}${q.unit ? ` ${q.unit}` : ''}`
}

export default function QuizPage() {
  const session = useSession()
  const [questions, setQuestions] = useState<QuizQuestion[]>([])
  const [step, setStep] = useState<Step>('intro')
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<QuizProfile | null>(null)

  useEffect(() => {
    fetchQuizQuestions()
      .then((qs) => {
        setQuestions(qs)
        // Always-included choices (bodyweight) start ticked.
        setAnswers((a) => {
          const next = { ...a }
          for (const q of qs) if (q.always_included && next[q.id] === undefined) next[q.id] = [q.always_included]
          return next
        })
      })
      .catch((e: Error) => setError(e.message))
  }, [])

  // Each step is a new screen on the same route, so the route-change scroll reset never fires: start every
  // step at the top here (Next, Back, the disclaimer, the review screen, and the thank-you screen).
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [step])

  const general = questions.filter((q) => !q.health && asked(q, answers))
  const health = questions.filter((q) => q.health && asked(q, answers))

  function check(qs: QuizQuestion[]): boolean {
    for (const q of qs) {
      if (q.required && !isAnswered(q, answers[q.id])) {
        setError(`Please answer: ${q.prompt}`)
        return false
      }
      const range = rangeError(q, answers[q.id])
      if (range) {
        setError(range)
        return false
      }
    }
    setError(null)
    return true
  }

  async function submit() {
    if (!session) return
    if (!consent) {
      setError('Please read and accept the medical disclaimer first.')
      setStep('consent')
      return
    }
    if (!check([...general, ...health])) return
    setSaving(true)
    try {
      // Only the questions that were asked (e.g. no weight unless the goal is losing weight).
      const visible = new Set([...general, ...health].map((q) => q.id))
      const filled = Object.fromEntries(
        Object.entries(answers).filter(([k, v]) => visible.has(k) && v !== '' && v !== undefined),
      )
      const profile = await submitQuiz(session.userId, session.token, {
        consent_accepted: consent,
        consent_version: CONSENT_VERSION,
        answers: filled,
      })
      // Pregnant / postpartum: straight to the support page, not the Dashboard (no plan or AI for them).
      if (profile.needs_clinical_review) {
        navigate('/pregnancy-support')
        return
      }
      setSaved(profile)
      setStep('done')
    } catch (e) {
      // Only a sign-in the server rejects ends the session. Anything else (a 500, a restart, no network)
      // keeps you signed in with your answers still on screen, so you can just press Submit again.
      if (isSignInGone(e)) setSession(null)
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  const set = (id: string) => (v: Answer) => setAnswers((a) => ({ ...a, [id]: v }))

  if (!session) {
    return (
      <>
        <h2 className="page-title">Get started</h2>
        <p>Create an account to save your quiz answers and plan.</p>
        <AccountForm />
      </>
    )
  }

  return (
    <>
      <h2 className="page-title">Your fitness quiz</h2>
      <p className="meta">Signed in as {session.username}</p>
      {/* The intro card comes before the quiz itself, so the quiz's step list appears once the questions start. */}
      {step === 'intro' && <SummerIntro onContinue={() => setStep('general')} />}
      {step !== 'intro' && (
        <ol className="steps">
          <li className={step === 'general' ? 'current' : ''}>Goal</li>
          <li className={step === 'consent' ? 'current' : ''}>Disclaimer</li>
          <li className={step === 'health' ? 'current' : ''}>Health</li>
          <li className={step === 'review' ? 'current' : ''}>Review</li>
          <li className={step === 'done' ? 'current' : ''}>Done</li>
        </ol>
      )}

      {step === 'general' && (
        <div className="quiz-step">
          {general.map((q) => (
            <QuestionField key={q.id} q={q} value={answers[q.id]} onChange={set(q.id)} />
          ))}
          {error && <p className="error">{error}</p>}
          <button className="btn" onClick={() => check(general) && setStep(consent ? 'health' : 'consent')}>
            Next
          </button>
        </div>
      )}

      {step === 'consent' && (
        <div className="quiz-step">
          <ConsentStep accepted={consent} onChange={setConsent} />
          {error && <p className="error">{error}</p>}
          <div className="button-row">
            <button className="btn-secondary" onClick={() => setStep('general')}>
              Back
            </button>
            <button
              className="btn"
              disabled={!consent}
              onClick={() => {
                setError(null)
                setStep('health')
              }}
            >
              I agree, continue
            </button>
          </div>
          {!consent && <p className="hint">Check the box above to continue to the health questions.</p>}
        </div>
      )}

      {step === 'health' && consent && (
        <div className="quiz-step">
          {health.map((q) => (
            <div key={q.id}>
              <QuestionField q={q} value={answers[q.id]} onChange={set(q.id)} />
              {q.pace_note && <PaceNote q={q} answers={answers} />}
            </div>
          ))}
          {error && <p className="error">{error}</p>}
          <div className="button-row">
            <button className="btn-secondary" onClick={() => setStep('consent')}>
              Back
            </button>
            <button className="btn" onClick={() => check(health) && setStep('review')}>
              Review my answers
            </button>
          </div>
        </div>
      )}

      {step === 'review' && consent && (
        <div className="quiz-step quiz-review">
          <h3>Review your answers</h3>
          <p className="hint">Check everything before you submit. Change anything you like.</p>
          {[
            { label: 'Your goal and setup', qs: general, back: 'general' as Step },
            { label: 'Health', qs: health, back: 'health' as Step },
          ].map((group) => (
            <section key={group.label} className="review-group" aria-label={group.label}>
              <div className="review-group-head">
                <h4>{group.label}</h4>
                <button type="button" className="btn-ghost btn-small" onClick={() => setStep(group.back)}>
                  Change
                </button>
              </div>
              <dl>
                {group.qs.map((q) => (
                  <div key={q.id} className="review-row">
                    <dt>{q.prompt}</dt>
                    <dd>{shown(q, answers[q.id])}</dd>
                  </div>
                ))}
              </dl>
            </section>
          ))}
          <p className="hint">Medical disclaimer: accepted.</p>
          {error && <p className="error">{error}</p>}
          <div className="button-row">
            <button className="btn-secondary" onClick={() => setStep('health')}>
              Back
            </button>
            <button className="btn" disabled={!consent || saving} onClick={submit}>
              {saving ? 'Saving…' : 'Submit quiz'}
            </button>
          </div>
        </div>
      )}

      {step === 'done' && saved && (
        <div className="quiz-step">
          <p className="success">Thanks! Your answers are saved.</p>
          <CalendarModeChooser token={session.token} current={saved.calendar_mode ?? 'generated'} />
          <p>
            Disclaimer accepted on {new Date(saved.consent_accepted_at).toLocaleString()}. You can review or delete
            your data any time in <Link to="/settings">Settings</Link>.
          </p>
          <Link to="/" className="btn btn-big">
            Go to my dashboard
          </Link>
        </div>
      )}
    </>
  )
}
