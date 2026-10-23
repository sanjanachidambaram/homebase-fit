// Onboarding quiz: account -> general questions -> REQUIRED medical disclaimer
// acknowledgment -> health/injury questions -> submit.
// Health questions (health: true in quiz_questions.yaml) stay hidden until the
// disclaimer is accepted, and the API rejects any submission without consent.
import { useEffect, useLayoutEffect, useState } from 'react'
import { fetchQuizQuestions, isSignInGone, submitQuiz, type QuizProfile, type QuizQuestion } from '../api'
import AccountForm from '../components/AccountForm'
import CalendarModeChooser from '../components/CalendarModeChooser'
import { ConsentStep } from '../components/Legal'
import { CONSENT_VERSION } from '../legal'
import Link from '../components/Link'
import { navigate } from '../router'
import { setSession, useSession } from '../session'

type Answer = string | number | string[] | ''
type Step = 'general' | 'consent' | 'health' | 'done'

function isAnswered(q: QuizQuestion, value: Answer | undefined): boolean {
  if (q.type === 'multi_select') return Array.isArray(value) && value.length > 0
  if (q.type === 'number') return typeof value === 'number' && Number.isFinite(value)
  return value !== undefined && value !== ''
}

/** 70 -> "5 ft 10 in" */
const feetInches = (inches: number) => `${Math.floor(inches / 12)} ft ${inches % 12} in`

function rangeError(q: QuizQuestion, value: Answer | undefined): string | null {
  if (q.type !== 'number' || typeof value !== 'number') return null
  if ((q.min !== undefined && value < q.min) || (q.max !== undefined && value > q.max)) {
    const show = (n: number | undefined) => (n !== undefined && q.input === 'feet_inches' ? feetInches(n) : n)
    return `"${q.prompt}" must be between ${show(q.min)} and ${show(q.max)}.`
  }
  return null
}

/** Height in feet + inches. The answer stays total inches (what the API and the plan use). */
function FeetInchesField({ q, value, onChange }: { q: QuizQuestion; value: Answer | undefined; onChange: (v: Answer) => void }) {
  const total = typeof value === 'number' ? value : null
  const [feet, setFeet] = useState(total === null ? '' : String(Math.floor(total / 12)))
  const [inches, setInches] = useState(total === null ? '' : String(total % 12))
  const update = (f: string, i: string) => {
    setFeet(f)
    setInches(i)
    onChange(f === '' ? '' : Number(f) * 12 + (i === '' ? 0 : Number(i)))
  }
  return (
    <fieldset className="question">
      <legend>{q.prompt}</legend>
      {q.help_text && <span className="hint question-help">{q.help_text}</span>}
      <span className="number-row">
        <input
          type="number"
          aria-label="Feet"
          className="short"
          min={Math.floor((q.min ?? 0) / 12)}
          max={Math.floor((q.max ?? 120) / 12)}
          value={feet}
          onChange={(e) => update(e.target.value, inches)}
        />
        <span className="unit">ft</span>
        <input
          type="number"
          aria-label="Inches"
          className="short"
          min={0}
          max={11}
          value={inches}
          onChange={(e) => update(feet, e.target.value)}
        />
        <span className="unit">in</span>
      </span>
    </fieldset>
  )
}

function OptionLabel({ label, description }: { label: string; description?: string }) {
  return (
    <span className="choice-text">
      <span>{label}</span>
      {description && <span className="choice-desc">{description}</span>}
    </span>
  )
}

/** Gentle, cited note (never a block) when a goal weight + date means losing faster than the guidance pace. */
function WeightPaceNote({ questions, answers }: { questions: QuizQuestion[]; answers: Record<string, Answer> }) {
  const [now] = useState(() => Date.now())   // read the clock once, not on every render
  const note = questions.find((q) => q.rate_note)?.rate_note
  const { weight, goal_weight: goal, goal_date: when } = answers
  if (!note || typeof weight !== 'number' || typeof goal !== 'number' || typeof when !== 'string' || !when) return null
  const weeks = (new Date(when).getTime() - now) / (7 * 24 * 3600 * 1000)
  const perWeek = (weight - goal) / weeks
  if (!(weeks > 0) || !(perWeek > note.max_lbs_per_week)) return null
  const [label, url] = note.source.split(/:\s(?=https?:)/)
  return (
    <div className="pace-note" role="note">
      <p>
        <strong>That works out to about {perWeek.toFixed(1)} lb a week.</strong> {note.text}
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

function QuestionField({
  q,
  value,
  onChange,
}: {
  q: QuizQuestion
  value: Answer | undefined
  onChange: (v: Answer) => void
}) {
  const [tomorrow] = useState(() => new Date(Date.now() + 24 * 3600 * 1000).toISOString().slice(0, 10))
  const help = q.help_text && <span className="hint question-help">{q.help_text}</span>
  if (q.type === 'number' && q.input === 'feet_inches') return <FeetInchesField q={q} value={value} onChange={onChange} />
  if (q.type === 'multi_select') {
    const selected = Array.isArray(value) ? value : []
    const toggle = (v: string, checked: boolean) => {
      if (!checked) return onChange(selected.filter((x) => x !== v))
      if (v === q.exclusive) return onChange([v]) // "None" clears the others
      onChange([...selected.filter((x) => x !== q.exclusive), v])
    }
    return (
      <fieldset className="question">
        <legend>{q.prompt}</legend>
        {help}
        {q.options.map((o) => (
          <label key={o.value} className="choice">
            <input
              type="checkbox"
              checked={selected.includes(o.value)}
              onChange={(e) => toggle(o.value, e.target.checked)}
            />
            <OptionLabel label={o.label} description={o.description} />
          </label>
        ))}
      </fieldset>
    )
  }
  if (q.type === 'single_select') {
    return (
      <fieldset className="question">
        <legend>{q.prompt}</legend>
        {help}
        {q.options.map((o) => (
          <label key={o.value} className="choice">
            <input type="radio" name={q.id} checked={value === o.value} onChange={() => onChange(o.value)} />
            <OptionLabel label={o.label} description={o.description} />
          </label>
        ))}
      </fieldset>
    )
  }
  return (
    <label className="question">
      <span className="legend">{q.prompt}</span>
      {help}
      <span className="number-row">
        <input
          type={q.type === 'number' ? 'number' : q.type === 'date' ? 'date' : 'text'}
          min={q.type === 'date' ? tomorrow : q.min}
          max={q.max}
          maxLength={q.type === 'text' ? 500 : undefined}
          value={value === undefined ? '' : String(value)}
          onChange={(e) => {
            const raw = e.target.value
            onChange(q.type === 'number' ? (raw === '' ? '' : Number(raw)) : raw)
          }}
        />
        {q.unit && <span className="unit">{q.unit}</span>}
      </span>
    </label>
  )
}

export default function QuizPage() {
  const session = useSession()
  const [questions, setQuestions] = useState<QuizQuestion[]>([])
  const [step, setStep] = useState<Step>('general')
  const [answers, setAnswers] = useState<Record<string, Answer>>({})
  const [injuryNotes, setInjuryNotes] = useState('')
  const [consent, setConsent] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState<QuizProfile | null>(null)

  useEffect(() => {
    fetchQuizQuestions()
      .then(setQuestions)
      .catch((e: Error) => setError(e.message))
  }, [])

  // Each step is a new screen on the same route, so the route-change scroll reset never fires: start every
  // step at the top here (Next, Back, the disclaimer, and the thank-you screen after submitting).
  useLayoutEffect(() => {
    window.scrollTo(0, 0)
  }, [step])

  const general = questions.filter((q) => !q.health)
  const health = questions.filter((q) => q.health)

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
      const filled = Object.fromEntries(Object.entries(answers).filter(([, v]) => v !== '' && v !== undefined))
      const profile = await submitQuiz(session.userId, session.token, {
        consent_accepted: consent,
        consent_version: CONSENT_VERSION,
        answers: filled,
        injury_notes: injuryNotes.trim() || undefined,
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
      <ol className="steps">
        <li className={step === 'general' ? 'current' : ''}>Goals</li>
        <li className={step === 'consent' ? 'current' : ''}>Disclaimer</li>
        <li className={step === 'health' ? 'current' : ''}>Health</li>
        <li className={step === 'done' ? 'current' : ''}>Done</li>
      </ol>

      {step === 'general' && (
        <div className="quiz-step">
          {general.map((q) => (
            <QuestionField key={q.id} q={q} value={answers[q.id]} onChange={set(q.id)} />
          ))}
          {error && <p className="error">{error}</p>}
          <button className="btn" onClick={() => check(general) && setStep('consent')}>
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
              {q.allow_free_text && (
                <label className="question">
                  <span className="legend">{q.free_text_prompt ?? 'Anything else?'}</span>
                  <textarea rows={3} maxLength={1000} value={injuryNotes} onChange={(e) => setInjuryNotes(e.target.value)} />
                  <span className="hint">This stays in our database and is never sent to the AI model.</span>
                </label>
              )}
              {q.id === 'goal_date' && <WeightPaceNote questions={questions} answers={answers} />}
            </div>
          ))}
          {error && <p className="error">{error}</p>}
          <div className="button-row">
            <button className="btn-secondary" onClick={() => setStep('consent')}>
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
