// Calendar: your generated plan on real dates, one week at a time. Drag a day onto another day to swap them
// (PATCH /api/calendar/{id} {date}), tick a workout off (writes the workout logs the Coach reads), and keep notes.
// Every day that isn't done or past shows one clear choice of what goes there: "Use my plan" (the generated day),
// "Build your own" (the Workout Builder, same injury filter), or "Add cardio" (done once you log cardio on it).
// The planned day is kept so "Use my plan" can bring it back, and a quiz retake never replaces a day you chose.
// Done days show a calorie range computed in code (never AI), and the progress marker at the top is code too: it
// only adds up numbers the app already computes. The full caveats live once, at the bottom (#calorie-estimates).
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
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react'
import {
  fetchCalendar,
  fetchCalendarProgress,
  isSignInGone,
  makeCardioDay,
  MUSCLE_GROUP_LABELS,
  overrideCalendarDay,
  reviewCalendarDay,
  updateCalendarDay,
  applyDayPlan,
  type CalendarEntry,
  type CalendarProgress,
  type CalendarRange,
  type PlanWindow,
} from '../api'
import AccountForm from '../components/AccountForm'
import CardioForm, { CardioList } from '../components/CardioLog'
import ClinicalSupportCard from '../components/ClinicalSupport'
import WorkoutBuilder from '../components/dashboard/WorkoutBuilder'
import ReviewWorkout from '../components/WorkoutReview'
import Link from '../components/Link'
import { setSession, useSession, type Session } from '../session'

const DAY_NAMES = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']

type LogRow = { exercise_id: string; reps?: number | null; weight_lb?: number | null }
type DayChange = { date?: string; notes?: string | null; completed?: boolean; log?: LogRow[] }

const firstInt = (s: string) => {
  const m = /\d+/.exec(s)
  return m ? Number(m[0]) : null
}

/** "Mark done" for a workout day: what you actually did. Reps for every exercise; weight only for exercises that use
 *  weights (bodyweight ones have no weight box, never a made-up zero). Weights start at the suggestion, which you can
 *  change. Week 1 is the calibration week: later suggestions build on what you log here. */
function LogDayForm({
  entry,
  busy,
  onSave,
  onCancel,
}: {
  entry: CalendarEntry
  busy: boolean
  onSave: (log: LogRow[]) => void
  onCancel: () => void
}) {
  const w = entry.workout
  const [rows, setRows] = useState(() =>
    w.exercises.map((x) => {
      const info = entry.weights[x.exercise_id]
      return {
        id: x.exercise_id,
        name: x.name,
        weighted: !!info?.weighted,
        reps: x.reps_your_call ? '' : String(firstInt(x.reps) ?? ''),
        weight: info?.suggested_lb != null ? String(info.suggested_lb) : '',
        timed: /\d\s*s\b|hold|sec/.test(x.reps), // holds and cardio intervals: no reps to count
      }
    }),
  )
  const set = (i: number, key: 'reps' | 'weight', v: string) =>
    setRows((r) => r.map((row, j) => (j === i ? { ...row, [key]: v } : row)))
  return (
    <form
      className="log-form"
      onSubmit={(e) => {
        e.preventDefault()
        onSave(
          rows.map((r) => ({
            exercise_id: r.id,
            reps: r.timed || r.reps === '' ? null : Number(r.reps),
            weight_lb: r.weighted && r.weight !== '' ? Number(r.weight) : null,
          })),
        )
      }}
    >
      {w.calibration_week && (
        <p className="hint">Calibration week: log what you actually did. Next time, suggestions build on it.</p>
      )}
      <table className="log-table">
        <thead>
          <tr>
            <th scope="col">Exercise</th>
            <th scope="col">Reps</th>
            <th scope="col">Weight (lb)</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r, i) => (
            <tr key={r.id}>
              <th scope="row">{r.name}</th>
              <td>
                {r.timed ? (
                  <span className="hint">timed</span>
                ) : (
                  <input
                    type="number"
                    min={0}
                    max={500}
                    aria-label={`Reps for ${r.name}`}
                    value={r.reps}
                    onChange={(e) => set(i, 'reps', e.target.value)}
                  />
                )}
              </td>
              <td>
                <input
                  type="number"
                  min={0}
                  max={1000}
                  step={0.5}
                  aria-label={`Weight for ${r.name}`}
                  placeholder={r.weighted ? 'lb' : 'bodyweight'}
                  disabled={!r.weighted}
                  value={r.weighted ? r.weight : ''}
                  onChange={(e) => set(i, 'weight', e.target.value)}
                />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="day-notes-actions">
        <button type="submit" className="btn-secondary btn-small" disabled={busy}>
          {busy ? 'Saving…' : 'Save as done'}
        </button>
        <button type="button" className="btn-link" onClick={onCancel}>
          Cancel
        </button>
      </div>
    </form>
  )
}

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
const longDate = (s: string) => parse(s).toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' })
/** The plan week a date falls in (week 1 = the 7 days from the day the plan started). */
const planWeekOf = (date: string, started: string) =>
  Math.floor((parse(date).getTime() - parse(started).getTime()) / (7 * 86400000)) + 1

/** Where the shown week sits in the 6-month plan, and a jump to any of its 26 weeks. */
function PlanBar({ plan, weekStart, onJump }: { plan: PlanWindow; weekStart: string; onJump: (date: string) => void }) {
  const weekEnd = addDays(weekStart, 6)
  const first = Math.max(1, planWeekOf(weekStart, plan.started_on))
  const last = Math.min(plan.weeks, planWeekOf(weekEnd, plan.started_on))
  let where: ReactNode
  if (weekEnd < plan.started_on) where = <>Your plan starts {longDate(plan.started_on)}.</>
  else if (weekStart > plan.ends_on)
    where = (
      <>
        Your 6-month plan ended {longDate(plan.ends_on)}. <Link to="/quiz">Retake the quiz</Link> to start a new one.
      </>
    )
  else where = first === last ? `Week ${first} of ${plan.weeks}` : `Weeks ${first}–${last} of ${plan.weeks}`
  return (
    <div className="plan-bar">
      <p>
        <strong>Your 6-month plan</strong> · {where}{' '}
        <span className="hint">
          ({longDate(plan.started_on)} – {longDate(plan.ends_on)})
        </span>
      </p>
      <label>
        Jump to{' '}
        <select value="" onChange={(e) => e.target.value && onJump(e.target.value)}>
          <option value="">a week of the plan…</option>
          {Array.from({ length: plan.weeks }, (_, i) => {
            const d = addDays(plan.started_on, 7 * i)
            return (
              <option key={i} value={d}>
                Week {i + 1} ({shortDate(d)})
              </option>
            )
          })}
        </select>
      </label>
    </div>
  )
}

// ---------------------------------------------------------------- one day

function DayCard({
  entry,
  busy,
  supportMessage,
  onChange,
  onBuild,
  onUsePlan,
  onCardio,
  onReview,
  cardio,
}: {
  entry: CalendarEntry
  cardio?: ReactNode // the cardio log for that date (on a strength day it doesn't tick the workout off)
  busy: boolean
  supportMessage: string | null
  onChange: (id: number, change: DayChange) => Promise<boolean>
  onBuild: (entry: CalendarEntry) => void
  onUsePlan: (entry: CalendarEntry) => void
  onCardio: (entry: CalendarEntry) => void
  onReview: (entry: CalendarEntry) => void
}) {
  const { attributes, listeners, setNodeRef, transform, isDragging } = useDraggable({
    id: entry.id,
    disabled: entry.completed || busy,
  })
  const [draft, setDraft] = useState(entry.notes ?? '')
  const [logging, setLogging] = useState(false)
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
      aria-label={`${dayName(entry.date)} ${shortDate(entry.date)}: ${
        entry.day_type === 'workout' ? 'workout' : entry.day_type === 'cardio' ? 'cardio day' : 'rest day'
      }`}
    >
      <div className="day-card-head">
        {/* A custom day's focus reads "Your own: ..." and gets the orange chip, so it's clear it was overridden. */}
        <span
          className={`chip chip-small ${
            entry.day_type === 'cardio'
              ? 'chip-cardio'
              : entry.source === 'custom'
                ? 'chip-custom'
                : entry.day_type === 'workout'
                  ? 'chip-workout'
                  : 'chip-rest'
          }`}
        >
          {entry.day_type === 'rest' ? (w.open ? 'Open day' : 'Rest day') : (w.focus ?? 'Workout')}
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

      {entry.can_override && (
        <div className="day-choice" role="group" aria-label="What goes on this day">
          <button
            type="button"
            className="day-choice-btn"
            aria-pressed={entry.choice === 'plan'}
            disabled={busy || entry.choice === 'plan'}
            onClick={() => onUsePlan(entry)}
          >
            Use my plan
          </button>
          <button type="button" className="day-choice-btn" aria-pressed={entry.choice === 'build'} disabled={busy} onClick={() => onBuild(entry)}>
            {entry.choice === 'build' ? 'Rebuild it' : 'Build your own'}
          </button>
          <button
            type="button"
            className="day-choice-btn"
            aria-pressed={entry.choice === 'cardio'}
            disabled={busy || entry.choice === 'cardio'}
            onClick={() => onCardio(entry)}
          >
            Add cardio
          </button>
        </div>
      )}
      {entry.calories && (
        <p className="day-kcal">
          <a href="#calorie-estimates" title="How we estimate calories">
            ~{entry.calories.low}–{entry.calories.high} kcal burned{entry.calories.rough ? ' (rough)' : ''}
          </a>
        </p>
      )}

      {entry.day_type === 'workout' ? (
        <>
          <p className="hint">
            About {Math.round(w.est_minutes)} min
            {w.week && entry.source === 'generated' ? ` · Week ${w.week}` : ''}
            {w.block_weeks && w.block_weeks > 1 && entry.source === 'generated'
              ? ` (week ${w.week_in_block} of the ${w.block_weeks}-week pattern)`
              : ''}
          </p>
          {w.calibration_week && entry.source === 'generated' && !entry.completed && (
            <p className="hint calibration-tag">Calibration week: the weights are just starting suggestions.</p>
          )}
          <ul className="day-exercises">
            {w.exercises.map((x) => {
              const info = entry.weights?.[x.exercise_id]
              return (
                <li key={x.exercise_id}>
                  <strong>{x.name}</strong>
                  <span>
                    {x.reps_your_call ? `${x.sets} sets × your call` : `${x.sets} × ${x.reps}`} ·{' '}
                    {MUSCLE_GROUP_LABELS[x.muscle_group] ?? x.muscle_group}
                    {info?.logged_lb != null || info?.logged_reps != null ? (
                      <>
                        {' '}
                        · did {info.logged_reps ?? '–'} reps{info.logged_lb != null ? ` at ${info.logged_lb} lb` : ''}
                      </>
                    ) : info?.weighted ? (
                      <> · {info.suggested_lb != null ? `try ${info.suggested_lb} lb` : 'pick a weight'}</>
                    ) : null}
                  </span>
                </li>
              )
            })}
          </ul>
          {w.notes?.map((note) => (
            <p key={note} className="hint day-builder-note">
              {note}
            </p>
          ))}
          <label className={`chip-check day-done-toggle${entry.completed ? ' chip-on' : ''}`}>
            <input
              type="checkbox"
              checked={entry.completed || logging}
              disabled={busy || (!entry.completed && !entry.can_complete)}
              onChange={(e) => {
                if (!e.target.checked) {
                  setLogging(false)
                  if (entry.completed) onChange(entry.id, { completed: false })
                } else if (w.exercises.length) setLogging(true) // log reps and weights first
                else onChange(entry.id, { completed: true })
              }}
            />
            {entry.completed ? 'Done!' : 'Mark done'}
          </label>
          {logging && !entry.completed && (
            <LogDayForm
              entry={entry}
              busy={busy}
              onCancel={() => setLogging(false)}
              onSave={async (log) => {
                if (await onChange(entry.id, { completed: true, log })) setLogging(false)
              }}
            />
          )}
          {!entry.completed && !entry.can_complete && <p className="hint">Tick it off on the day.</p>}
          {cardio}
        </>
      ) : entry.day_type === 'cardio' ? (
        <>
          <p className="rest-text">
            {entry.completed
              ? 'Cardio done. Nice work showing up!'
              : entry.source === 'generated'
                ? 'Any cardio you like: walk, run, bike, dance. Log what you did and it counts as done.'
                : 'Cardio day: log what you did and it counts as done.'}
          </p>
          {/* A status line, not a toggle: a cardio day is done by logging cardio, so it shouldn't look clickable. */}
          <p className={`day-cardio-status${entry.completed ? ' is-done' : ''}`} aria-live="polite">
            {entry.completed ? 'Logged ✓' : 'Not logged yet'}
          </p>
          {cardio}
        </>
      ) : (
        <>
          <p className="rest-text">
            {w.open
              ? 'Open day: pick what goes here above, or just log some cardio.'
              : 'Rest and recover. Your muscles get stronger on days like this.'}
          </p>
          {cardio}
        </>
      )}

      {entry.choice === 'build' && (
        <div className="day-custom-actions">
          <button type="button" className="btn-ghost btn-small" disabled={busy} onClick={() => onReview(entry)}>
            Review this workout
          </button>
        </div>
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

/** The one place on the calendar with the full caveats behind every calorie and pound figure (linked from each). */
function CalorieCaveats() {
  return (
    <section id="calorie-estimates" className="calorie-caveats" aria-labelledby="calorie-estimates-title">
      <h3 id="calorie-estimates-title">How we estimate calories</h3>
      <ul>
        <li>
          Calories are worked out by the app's own math, never by AI: MET values from the 2024 Adult Compendium of
          Physical Activities times your weight from the quiz times the time spent (about 1 calorie per kilogram per hour
          for each MET). The Compendium itself says its values don't reflect precise individual energy use.
        </li>
        <li>
          Every number is a range: an easier and a harder way of doing the same thing. Where you land depends on how hard
          you worked.
        </li>
        <li>
          Distance uses the Compendium's speed-specific values for walking, running and cycling. Steps are turned into
          distance with a rough rule of thumb (about 2,000 to 2,500 steps a mile), so those are extra rough.
        </li>
        <li>
          Pound figures (weight-loss goals only) use the 3,500-calories-per-pound rule of thumb: a rough, long-used
          approximation, not a precise prediction. Exercise on its own is usually a small piece of weight change compared
          with eating habits; sleep and stress play a part too.
        </li>
      </ul>
      <p className="hint">
        Sources: see <Link to="/about/data">where our data comes from</Link>.
      </p>
    </section>
  )
}

/** A modal with the Workout Reviewer for one custom day. */
function ReviewDayModal({ entry, token, onClose }: { entry: CalendarEntry; token: string; onClose: () => void }) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      opener?.focus()
    }
  }, [onClose])
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="review-day-title" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <h2 id="review-day-title">
            Review: {dayName(entry.date)} {shortDate(entry.date)}
          </h2>
          <button ref={closeRef} type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <ReviewWorkout load={() => reviewCalendarDay(token, entry.id)} />
      </div>
    </div>
  )
}

/** The existing Build Your Own form in a modal, saving onto one calendar day. */
function BuildDayModal({
  entry,
  token,
  onClose,
  onSaved,
}: {
  entry: CalendarEntry
  token: string
  onClose: () => void
  onSaved: () => void
}) {
  const closeRef = useRef<HTMLButtonElement>(null)
  useEffect(() => {
    const opener = document.activeElement as HTMLElement | null
    closeRef.current?.focus()
    const previousOverflow = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = previousOverflow
      opener?.focus()
    }
  }, [onClose])

  const replacing =
    entry.source === 'custom' ? 'the workout you built' : entry.day_type === 'rest' ? 'the planned rest day' : 'the planned workout'
  return (
    <div className="modal-overlay" onClick={onClose}>
      <div
        className="modal build-day-modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="build-day-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="build-day-title">
            Build your own for {dayName(entry.date)} {shortDate(entry.date)}
          </h2>
          <button ref={closeRef} type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>
        <p className="hint">
          This replaces {replacing} for this day. You can switch back to the planned one any time before the day is
          done, and retaking the quiz won't replace a day you built. The same injury filter applies as always.
        </p>
        <WorkoutBuilder
          token={token}
          compact
          title="Pick your moves"
          submitLabel="Build and save to this day"
          build={async (req) => (await overrideCalendarDay(token, entry.id, req)).result}
          onBuilt={onSaved}
        />
      </div>
    </div>
  )
}

// ---------------------------------------------------------------- the week

function Calendar({ session }: { session: Session }) {
  const [weekStart, setWeekStart] = useState(() => mondayOf(new Date()))
  const [data, setData] = useState<CalendarRange | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [support, setSupport] = useState<Record<number, string>>({})
  const [buildingFor, setBuildingFor] = useState<CalendarEntry | null>(null)
  const [reviewingFor, setReviewingFor] = useState<CalendarEntry | null>(null)
  const closeReview = useCallback(() => setReviewingFor(null), [])
  const [notice, setNotice] = useState<string | null>(null)
  const [progress, setProgress] = useState<CalendarProgress | null>(null)
  const weekEnd = addDays(weekStart, 6)
  const closeBuilder = useCallback(() => setBuildingFor(null), [])

  const load = useCallback(
    () =>
      Promise.all([
        fetchCalendar(session.token, weekStart, weekEnd),
        fetchCalendarProgress(session.token, weekStart).catch(() => null), // the marker is extra: never blocks
      ])
        .then(([d, p]) => {
          setData(d)
          setProgress(p)
          setError(null)
        })
        .catch((e: Error) => {
          if (isSignInGone(e)) setSession(null)
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

  async function change(id: number, body: DayChange) {
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

  /** The day-type selector's "Use my plan" and "Add cardio" (Build your own opens the builder). No AI. */
  async function choose(entry: CalendarEntry, pick: 'plan' | 'cardio') {
    setBusyId(entry.id)
    setError(null)
    setNotice(null)
    try {
      const r = pick === 'plan' ? await applyDayPlan(session.token, entry.id) : await makeCardioDay(session.token, entry.id, null)
      const when = `${dayName(r.entry.date)} ${shortDate(r.entry.date)}`
      setNotice(
        pick === 'cardio'
          ? `${when} is a cardio day. Log what you did on the day and it counts as done.`
          : `${when} is back to your plan${r.entry.day_type === 'rest' ? ' (a rest day)' : ''}.`,
      )
      await load()
    } catch (e) {
      if (isSignInGone(e)) setSession(null)
      setError((e as Error).message)
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
  const loggable = (date: string) => !!data && date <= addDays(data.today, 1) // not ahead of time
  const cardioFor = (date: string, allowLibrary: boolean) => (
    <div className="day-cardio">
      <CardioList logs={(data?.cardio ?? []).filter((c) => c.date === date)} token={session.token} onChange={load} />
      {loggable(date) && <CardioForm token={session.token} date={date} allowLibrary={allowLibrary} onLogged={load} />}
    </div>
  )

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
      {data?.plan && <PlanBar plan={data.plan} weekStart={weekStart} onJump={(d) => setWeekStart(mondayOf(parse(d)))} />}

      {progress?.available && progress.items && (
        <section className="dash-card progress-marker" aria-labelledby="progress-title">
          <h3 id="progress-title">{progress.headline}</h3>
          <ul>
            {progress.items.map((i) => (
              <li key={i.kind} className={`progress-${i.kind}`}>
                {i.text}{' '}
                {i.anchor && (
                  <a href={`#${i.anchor}`} className="hint">
                    how we estimate
                  </a>
                )}
              </li>
            ))}
          </ul>
          <p className="hint">Worked out by the app's own math from what you've logged, not by AI.</p>
        </section>
      )}

      {error && <p className="error">{error}</p>}
      {notice && (
        <p className="success" role="status">
          {notice}
        </p>
      )}
      {!data && !error && <p className="hint">Loading your week…</p>}

      {data?.needs_clinical_review && (
        <>
          <ClinicalSupportCard />
          {/* No plan or workouts for them, but their own activity log works (shared_rules rule 9): own words only. */}
          <section className="dash-card activity-log" aria-labelledby="activity-log-title">
            <h3 id="activity-log-title">Your activity log</h3>
            <p className="hint">
              Keep a note of the activity your OB-GYN or midwife has okayed. It’s just for you: no AI, and never shared.
            </p>
            <ul className="activity-days">
              {days.map((date) => (
                <li key={date}>
                  <strong>
                    {dayName(date).slice(0, 3)} {shortDate(date)}
                  </strong>
                  {cardioFor(date, false)}
                </li>
              ))}
            </ul>
          </section>
        </>
      )}

      {data?.needs_review && (
        <section className="dash-card quiz-prompt">
          <h3>Your plan is waiting for your review</h3>
          <p>You chose to review your plan before it goes on the calendar. Swap anything you like, then add it.</p>
          <Link to="/plan/review" className="btn btn-big">
            Review my plan
          </Link>
        </section>
      )}

      {data?.needs_quiz && (
        <section className="dash-card quiz-prompt">
          <h3>Take the quiz to fill your calendar</h3>
          <p>We'll lay out your 6-month plan here, built from your goal, experience, equipment and any injuries.</p>
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
                        onBuild={(x) => {
                          setNotice(null)
                          setBuildingFor(x)
                        }}
                        onUsePlan={(x) => choose(x, 'plan')}
                        onCardio={(x) => choose(x, 'cardio')}
                        onReview={setReviewingFor}
                        cardio={cardioFor(date, true)}
                      />
                    ) : (
                      <>
                        <p className="hint day-empty">Nothing planned</p>
                        {cardioFor(date, true)}
                      </>
                    )}
                  </DayCell>
                )
              })}
            </div>
          </DndContext>
          {reviewingFor && (
            <ReviewDayModal key={reviewingFor.id} entry={reviewingFor} token={session.token} onClose={closeReview} />
          )}
          {buildingFor && (
            <BuildDayModal
              key={buildingFor.id}
              entry={buildingFor}
              token={session.token}
              onClose={closeBuilder}
              onSaved={() => {
                setNotice(`Saved your own workout to ${dayName(buildingFor.date)} ${shortDate(buildingFor.date)}.`)
                setBuildingFor(null)
                load()
              }}
            />
          )}
          {data.entries.length === 0 && (
            <p className="hint">
              Your plan covers 6 months from when you took the quiz. Retake it any time for a fresh 6 months;
              days you've marked done or written notes on are kept.
            </p>
          )}
          <CalorieCaveats />
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
