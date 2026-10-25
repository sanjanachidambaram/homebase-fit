// "Save to calendar" for a session built on the Build Your Own page. Lists your upcoming days that can take it (not
// done, today or later); any later date works too, and the calendar is extended to it. The server saves the session
// exactly as the Workout Builder made it (we only send its id) through the same custom-day mechanism.
import { useEffect, useState } from 'react'
import { fetchCalendar, saveBuiltToCalendar, type CalendarEntry } from '../api'
import Link from './Link'

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const nice = (s: string) => new Date(`${s}T12:00:00`).toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })

function label(e: CalendarEntry) {
  const what =
    e.day_type === 'cardio'
      ? e.source === 'generated'
        ? 'cardio of your choice'
        : 'cardio day'
      : e.source === 'custom'
        ? 'your own workout'
        : e.workout.open
          ? 'open'
          : e.day_type === 'rest'
            ? 'rest day'
            : e.workout.focus
  return `${nice(e.date)} (${what})`
}

export default function SaveToCalendar({ token, builtId }: { token: string; builtId: number }) {
  const [days, setDays] = useState<CalendarEntry[] | null>(null)
  const [minDate] = useState(() => iso(new Date())) // today, fixed for this form
  const [date, setDate] = useState('')
  const [other, setOther] = useState('')
  const [saved, setSaved] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const start = new Date()
    const end = new Date()
    end.setDate(end.getDate() + 27)
    fetchCalendar(token, iso(start), iso(end))
      .then((r) => setDays(r.entries.filter((e) => e.can_override)))
      .catch(() => setDays([]))
  }, [token])

  async function save() {
    const target = date === 'other' ? other : date
    if (!target) return
    setBusy(true)
    setError(null)
    try {
      const r = await saveBuiltToCalendar(token, builtId, target)
      setSaved(r.entry.date)
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setBusy(false)
    }
  }

  if (saved) {
    return (
      <p className="success" role="status">
        Saved to {nice(saved)}. <Link to="/calendar">See it on your calendar →</Link> (You can switch that day back to
        the planned one any time before it’s done.)
      </p>
    )
  }
  return (
    <section className="save-to-calendar" aria-label="Save to calendar">
      <h4>Save to calendar</h4>
      <div className="controls">
        <label htmlFor="save-day">Day</label>
        <select id="save-day" value={date} onChange={(e) => setDate(e.target.value)} disabled={days === null}>
          <option value="">{days === null ? 'Loading your days…' : 'Pick a day'}</option>
          {days?.map((e) => (
            <option key={e.id} value={e.date}>
              {label(e)}
            </option>
          ))}
          <option value="other">A later date…</option>
        </select>
        {date === 'other' && (
          <input type="date" aria-label="Later date" value={other} min={minDate} onChange={(e) => setOther(e.target.value)} />
        )}
        <button type="button" className="btn" disabled={busy || !date || (date === 'other' && !other)} onClick={save}>
          {busy ? 'Saving…' : 'Save'}
        </button>
      </div>
      <p className="hint">This replaces what’s planned that day; the planned workout is kept so you can switch back.</p>
      {error && <p className="error">{error}</p>}
    </section>
  )
}
