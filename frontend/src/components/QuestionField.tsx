// One quiz question (single choice, multiple choice, or a number), as the onboarding quiz shows it. Shared with the
// Exercise Library, whose filters read like the quiz: a workout area to focus on, and body areas to avoid.
import type { QuizQuestion } from '../api'

export type Answer = string | number | string[] | ''

function OptionLabel({ label, description }: { label: string; description?: string }) {
  return (
    <span className="choice-text">
      <span>{label}</span>
      {description && <span className="choice-desc">{description}</span>}
    </span>
  )
}

export default function QuestionField({
  q,
  value,
  onChange,
}: {
  q: QuizQuestion
  value: Answer | undefined
  onChange: (v: Answer) => void
}) {
  const help = q.help_text && <span className="hint question-help">{q.help_text}</span>
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
        {q.options.map((o) => {
          const always = o.value === q.always_included // e.g. bodyweight: always on
          return (
            <label key={o.value} className="choice">
              <input
                type="checkbox"
                checked={always || selected.includes(o.value)}
                disabled={always}
                onChange={(e) => toggle(o.value, e.target.checked)}
              />
              <OptionLabel label={o.label} description={o.description} />
            </label>
          )
        })}
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
          type={q.type === 'number' ? 'number' : 'text'}
          min={q.min}
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
