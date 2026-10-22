// Calendar: your generated plan on real dates, one week at a time. Drag a day onto another day to swap them
// (PATCH /api/calendar/{id} {date}), tick a workout off (writes the workout logs the Coach reads), and keep notes.
// Notes stay private: they're never sent to the AI. A note that mentions pain or other warning signs is still
// saved, and the API (plain code, no AI) sends back a message pointing you to a doctor or physical therapist.
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  TouchSensor,
  useDraggable,
  useDroppable,
  useSensor,
  useSensors,
  type DragEndEvent,
} from '@dnd-kit/core'
import { useCallback, useEffect, useState, type ReactNode } from 'react'
import {
  fetchCalendar,
  MUSCLE_GROUP_LABELS,
  updateCalendarDay,
  type CalendarEntry,
  type CalendarRange,
} from '../api'
import AccountForm from '../components/AccountForm'
import ClinicalSupportCard from '../components/ClinicalSupport'
import Link from '../components/Link'
import { setSession, useSession, type Session } from '../session'

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

const pad = (n: number) => String(n).padStart(2, '0')
const iso = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
const parse = (s: string) => new Date(`${s}T12:00:00`) // noon: safe from DST edges
function addDays(s: string, n: number): string {
  const d = parse(s)
  d.setDate(d.getDate() + n)
  return iso(d)
}
function mondayOf(d: Date): string {
  const day = (d.getDay() + 6) % 7 // Monday = 0
  return addDays(iso(d), -day)
}
const dayName = (s: string) => DAY_NAMES[(parse(s).getDay() + 6) % 7] // Monday first
const shortDate = (s: string) => parse(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })

// ---------------------------------------------------------------- one day

function DayCard({
  entry,
  busy,
  supportMessage,
  onChange,
}: {
  entry: CalendarEntry
  busy: boolean
  supportMessage: string | null
  onChange: (id: number, change: { notes?: string | null; completed?: boolean }) => Promise<boolean>
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: entry.id,
    disabled: entry.completed || busy,
  })
  const [draft, setDraft] = useState(entry.notes ?? '')
  const [saved, setSaved] = useState(false)
  const dirty = draft.trim() !== (entry.notes ?? '')
  const w = entry.workout

  async function saveNote() {
    setSaved(false)
    if (await onChange(entry.id, { notes: draft.trim() || null })) setSaved(true)
  }

  return (
    <article
      ref={setNodeRef}
      className={`day-card day-${entry.day_type}${entry.completed ? ' day-done' : ''}${isDragging ? ' day-dragging' : ''}`}
      style={transform ? { transform: `translate3d(${transform.x}px, ${transform.y}px, 0)` } : undefined}
      aria-label={`${dayName(entry.date)} ${shortDate(entry.date)}: ${entry.day_type === 'workout' ? 'workout' : 'rest day'}`}
    >
      <div className="day-card-head">
        <span className={`chip chip-small ${entry.day_type === 'workout' ? 'chip-workout' : 'chip-rest'}`}>
          {entry.day_type === 'workout' ? (w.focus ?? 'Workout') : 'Rest day'}
        </span>
        {entry.completed ? (
          <span className="day-locked" title="Done days stay on their date">
            Done ✓
          </span>
        ) : (
          <button type="button" className="drag-handle" {...listeners} {...attributes} aria-label="Drag to move this day" title="Drag to move this day">
            ⠿
          </button>
        )}
      </div>

      {entry.day_type === 'workout' ? (
        <>
          <p className="hint">About {Math.round(w.est_minutes)} min</p>
          <ul className="day-exercises">
            {w.exercises.map((x) => (
              <li key={x.exercise_id}>
                <strong>{x.name}</strong>
                <span>
                  {x.sets} × {x.reps} · {MUSCLE_GROUP_LABELS[x.muscle_group] ?? x.muscle_group}
                </span>
              </li>
            ))}
          </ul>
          <label className={`chip-check day-done-toggle${entry.completed ? ' chip-on' : ''}`}>
            <input
              type="checkbox"
              checked={entry.completed}
              disabled={busy || (!entry.completed && !entry.can_complete)}
              onChange={(e) => onChange(entry.id, { completed: e.target.checked })}
            />
            {entry.completed ? 'Done!' : 'Mark done'}
          </label>
          {!entry.completed && !entry.can_complete && <p className="hint">Tick it off on the day.</p>}
        </>
      ) : (
        <p className="rest-text">Rest and recover. Your muscles get stronger on days like this.</p>
      )}

      <label className="day-notes">
        <span>Notes</span>
        <textarea
          rows={2}
          maxLength={2000}
          value={draft}
          placeholder="How did it go?"
          onChange={(e) => {
            setDraft(e.target.value)
            setSaved(false)
          }}
        />
      </label>
      <div className="day-notes-actions">
        <button type="button" className="btn-secondary btn-small" disabled={!dirty || busy} onClick={saveNote}>
          Save note
        </button>
        {saved && !dirty && <span className="hint">Saved</span>}
      </div>
      {supportMessage && (
        <p className="note-support" role="status">
          {supportMessage}
        </p>
      )}
    </article>
  )
}

function DayCell({ date, isToday, children }: { date: string; isToday: boolean; children: ReactNode }) {
  const { setNodeRef, isOver } = useDroppable({ id: date })
  return (
    <section
      ref={setNodeRef}
      className={`day-cell${isOver ? ' day-over' : ''}${isToday ? ' day-today' : ''}`}
      aria-label={`${dayName(date)} ${shortDate(date)}`}
    >
      <h3 className="day-cell-title">
        {dayName(date).slice(0, 3)} <span>{shortDate(date)}</span>
        {isToday && <span className="today-pill">Today</span>}
      </h3>
      {children}
    </section>
  )
}

// ---------------------------------------------------------------- the week

function Calendar({ session }: { session: Session }) {
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()))
  const [data, setData] = useState<CalendarRange | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [support, setSupport] = useState<Record<number, string>>({})
  const weekEnd = addDays(weekStart, 6)

  const load = useCallback(
    () =>
      fetchCalendar(session.token, weekStart, weekEnd)
        .then((d) => {
          setData(d)
          setError(null)
        })
        .catch((e: Error) => {
          if (/sign in/i.test(e.message)) setSession(null)
          setError(e.message)
        }),
    [session.token, weekStart, weekEnd],
  )

  useEffect(() => {
    load()
  }, [load])

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 8 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 200, tolerance: 6 } }),
    useSensor(KeyboardSensor),
  )

  async function change(id: number, body: { date?: string; notes?: string | null; completed?: boolean }) {
    setBusyId(id)
    setError(null)
    try {
      const r = await updateCalendarDay(session.token, id, body)
      if ('notes' in body) {
        setSupport((s) => {
          const next = { ...s }
          if (r.safety.flagged && r.safety.message) next[id] = r.safety.message
          else delete next[id]
          return next
        })
      }
      await load()
      return true
    } catch (e) {
      setError((e as Error).message)
      return false
    } finally {
      setBusyId(null)
    }
  }

  function onDragEnd(e: DragEndEvent) {
    const id = Number(e.active.id)
    const target = e.over ? String(e.over.id) : null
    const entry = data?.entries.find((x) => x.id === id)
    if (!entry || !target || target === entry.date) return
    // Show the move right away; the server swaps the two days (or refuses) and we reload either way.
    setData((d) =>
      d && {
        ...d,
        entries: d.entries.map((x) =>
          x.id === id ? { ...x, date: target } : x.date === target ? { ...x, date: entry.date } : x,
        ),
      },
    )
    change(id, { date: target })
  }

  const days = Array.from({ length: 7 }, (_, i) => addDays(weekStart, i))
  const byDate = new Map((data?.entries ?? []).map((e) => [e.date, e]))

  return (
    <div className="calendar">
      <div className="calendar-nav">
        <button type="button" className="btn-secondary" onClick={() => setWeekStart((w) => addDays(w, -7))}>
          ← Previous week
        </button>
        <strong className="calendar-range">
          {shortDate(weekStart)} – {shortDate(weekEnd)}
        </strong>
        <button type="button" className="btn-secondary" onClick={() => setWeekStart((w) => addDays(w, 7))}>
          Next week →
        </button>
        <button type="button" className="btn-ghost" onClick={() => setWeekStart(mondayOf(new Date()))}>
          This week
        </button>
      </div>

      {error && <p className="error">{error}</p>}
      {!data && !error && <p className="hint">Loading your week…</p>}

      {data?.needs_clinical_review && <ClinicalSupportCard />}

      {data?.needs_quiz && (
        <section className="dash-card quiz-prompt">
          <h3>Take the quiz to fill your calendar</h3>
          <p>We'll lay out four weeks of your plan here, built from your goals, time, equipment and any injuries.</p>
          <Link to="/quiz" className="btn btn-big">
            Take the quiz
          </Link>
        </section>
      )}

      {data && !data.needs_clinical_review && !data.needs_quiz && (
        <>
          <p className="hint">
            Drag a day by its <strong>⠿</strong> handle onto another day to swap them. Notes are private and never
            sent to the AI.
          </p>
          <DndContext sensors={sensors} onDragEnd={onDragEnd}>
            <div className="week-grid">
              {days.map((date) => {
                const entry = byDate.get(date)
                return (
                  <DayCell key={date} date={date} isToday={date === data.today}>
                    {entry ? (
                      <DayCard
                        key={entry.id}
                        entry={entry}
                        busy={busyId !== null}
                        supportMessage={support[entry.id] ?? null}
                        onChange={change}
                      />
                    ) : (
                      <p className="hint day-empty">Nothing planned</p>
                    )}
                  </DayCell>
                )
              })}
            </div>
          </DndContext>
          {data.entries.length === 0 && (
            <p className="hint">
              Your calendar covers four weeks from when you took the quiz. Retake it any time for a fresh four weeks;
              days you've marked done or written notes on are kept.
            </p>
          )}
        </>
      )}
    </div>
  )
}

export default function CalendarPage() {
  const session = useSession()
  return (
    <>
      <h2 className="page-title">Calendar</h2>
      <p className="page-sub">Your plan, day by day. Move days around when life happens.</p>
      {session ? (
        <Calendar key={session.userId} session={session} />
      ) : (
        <>
          <p>Sign in to see your calendar.</p>
          <AccountForm initialMode="login" />
        </>
      )}
    </>
  )
}
