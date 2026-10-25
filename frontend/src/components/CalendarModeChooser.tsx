// "How do you want to populate your calendar?" Shown after the quiz and in Settings. All three keep per-day
// overrides ("Build your own for this day"), and days you completed, wrote on or built are never replaced.
import { useState } from 'react'
import { isSignInGone, setCalendarMode, type CalendarMode } from '../api'
import { setSession } from '../session'
import Link from './Link'

const OPTIONS: { mode: CalendarMode; title: string; text: string }[] = [
  { mode: 'generated', title: 'Use my quiz plan', text: 'We lay out your generated 6-month plan, day by day. You can still change any day.' },
  {
    mode: 'review',
    title: 'Let me review it first',
    text: 'See your plan and swap exercises you don’t love (only for ones that pass the same safety checks), then put it on the calendar.',
  },
  { mode: 'self', title: 'I’ll build it myself', text: 'Your days start open. Fill them with Build Your Own whenever you like.' },
]

export default function CalendarModeChooser({
  token,
  current,
  onSaved,
}: {
  token: string
  current: CalendarMode
  onSaved?: (mode: CalendarMode) => void
}) {
  const [mode, setMode] = useState<CalendarMode>(current)
  const [saved, setSaved] = useState<CalendarMode | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await setCalendarMode(token, mode)
      setSaved(mode)
      onSaved?.(mode)
    } catch (e) {
      if (isSignInGone(e)) setSession(null)
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <fieldset className="mode-chooser">
      <legend>How do you want to populate your calendar?</legend>
      <div className="mode-options">
        {OPTIONS.map((o) => (
          <label key={o.mode} className={`mode-option${mode === o.mode ? ' mode-on' : ''}`}>
            <input type="radio" name="calendar-mode" value={o.mode} checked={mode === o.mode} onChange={() => setMode(o.mode)} />
            <strong>{o.title}</strong>
            <span>{o.text}</span>
          </label>
        ))}
      </div>
      <div className="button-row">
        <button type="button" className="btn" disabled={busy || mode === saved} onClick={save}>
          {busy ? 'Saving…' : 'Save my choice'}
        </button>
        {saved === 'review' && (
          <Link to="/plan/review" className="btn-secondary">
            Review my plan →
          </Link>
        )}
        {saved && saved !== 'review' && (
          <Link to="/calendar" className="btn-secondary">
            Go to my calendar →
          </Link>
        )}
      </div>
      {saved && <p className="success" role="status">Saved. Your calendar now follows this choice.</p>}
      {error && <p className="error">{error}</p>}
    </fieldset>
  )
}
