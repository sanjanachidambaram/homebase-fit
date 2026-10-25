// "View my quiz answers": the answers you submitted, read back from your saved quiz profile (GET /api/users/{id}, which
// the Dashboard already loads) and labeled with the quiz's own questions and options (GET /api/quiz/questions).
import { useEffect, useState } from 'react'
import { fetchQuizQuestions, type QuizProfile, type QuizQuestion } from '../../api'
import Link from '../Link'

// Quiz question id -> where the answer is saved (mirrors backend app/users.py QUIZ_COLUMNS).
const SAVED_AS: Record<string, keyof QuizProfile> = {
  goal: 'goal',
  experience_level: 'experience_level',
  equipment: 'equipment',
  injuries: 'injury_flags',
  pregnancy_status: 'pregnancy_status',
  weight: 'weight',
  goal_weight: 'goal_weight',
}

/** One question's saved answer as text, using the option labels the quiz showed. null = not answered / not asked. */
export function answerText(q: QuizQuestion, value: unknown): string | null {
  const label = (v: unknown) => q.options.find((o) => o.value === v)?.label ?? String(v)
  if (value === null || value === undefined || value === '') return null
  if (Array.isArray(value)) {
    if (value.length === 0) return q.id === 'injuries' ? label('none') : null
    return value.map(label).join(', ')
  }
  if (typeof value === 'number') return q.unit ? `${value} ${q.unit}` : String(value)
  return label(value)
}

export default function QuizAnswers({ profile }: { profile: QuizProfile }) {
  const [questions, setQuestions] = useState<QuizQuestion[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (!open || questions) return
    let cancelled = false
    fetchQuizQuestions()
      .then((qs) => !cancelled && setQuestions(qs))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [open, questions])

  const rows = (questions ?? [])
    .filter((q) => q.id in SAVED_AS)
    .map((q) => ({ q, text: answerText(q, profile[SAVED_AS[q.id]]) }))
    .filter((r) => r.text !== null)

  return (
    <details className="dash-card quiz-answers" onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}>
      <summary>View my quiz answers</summary>
      {error && <p className="error">{error}</p>}
      {open && !questions && !error && <p className="meta">Loading your answers…</p>}
      {questions && (
        <>
          <dl className="answer-list">
            {rows.map(({ q, text }) => (
              <div key={q.id}>
                <dt>{q.prompt}</dt>
                <dd>{text}</dd>
              </div>
            ))}
          </dl>
          <p className="hint">
            Submitted {new Date(profile.updated_at).toLocaleDateString()}. Want to change something?{' '}
            <Link to="/quiz">Retake the quiz</Link> (it gives you a fresh plan).
          </p>
        </>
      )}
    </details>
  )
}
