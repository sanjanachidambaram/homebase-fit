// "Ask the Basics": POST /api/basics/ask. Pain/injury questions get a plain "see a professional" reply (no AI involved).
import { useState, type FormEvent } from 'react'
import { askBasics, type BasicsAnswer } from '../../api'
import { agentError } from '../../agentCalls'
import ReviewInfo from '../ReviewInfo'
import Loading from './Loading'

const EXAMPLES = ['How long should I rest between sets?', 'What is progressive overload?', 'How do I track weight loss?']

export default function AskBasics({ token }: { token: string }) {
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<BasicsAnswer | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function ask(q: string) {
    if (q.trim().length < 3) return
    setLoading(true)
    setError(null)
    setAnswer(null)
    try {
      setAnswer((await askBasics(token, q.trim())).result)
    } catch (e) {
      setError(agentError(e))
    } finally {
      setLoading(false)
    }
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    ask(question)
  }

  return (
    <section className="dash-card ask-card" aria-labelledby="ask-title">
      <div className="dash-card-head">
        <h3 id="ask-title">
          Ask the Basics
        </h3>
      </div>
      <form onSubmit={submit} className="ask-form">
        <label htmlFor="ask-input" className="sr-only">
          Your question
        </label>
        <input
          id="ask-input"
          type="text"
          maxLength={500}
          placeholder="e.g. How long should I rest between sets?"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
        />
        <button type="submit" className="btn" disabled={loading || question.trim().length < 3}>
          Ask
        </button>
      </form>
      <div className="chip-row">
        {EXAMPLES.map((q) => (
          <button
            key={q}
            type="button"
            className="chip chip-button"
            onClick={() => {
              setQuestion(q)
              ask(q)
            }}
          >
            {q}
          </button>
        ))}
      </div>
      <p className="hint">Answers come only from our Fitness Basics guide.</p>

      {loading && <Loading text="Looking it up in our guide…" />}
      {error && <p className="error">{error}</p>}

      {answer?.redirected_to_professional && (
        <div className="safety-box" role="alert">
          <strong>Please check with a professional</strong>
          <p>{answer.answer}</p>
        </div>
      )}
      {answer && !answer.redirected_to_professional && (
        <div className="answer">
          <p>{answer.answer}</p>
          {answer.sources.map((s) => (
            <div key={s.slug} className="answer-source">
              <span className="hint">From our guide: {s.title}</span>
              <ReviewInfo item={s} />
            </div>
          ))}
          {answer.review_note && <p className="pending-note">{answer.review_note}</p>}
        </div>
      )}
    </section>
  )
}
