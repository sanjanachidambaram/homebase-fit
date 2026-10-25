// The Exercise Library. Its filters read like the onboarding quiz (and use the quiz's own question component):
// "What do you want to work on?" (the plans' groups: upper body, lower body, core / mobility) and "Any areas to
// avoid because of an injury?" (the quiz's injury list). The API does the filtering; avoiding an area runs through
// the same safety search as the plan generator, so exercises tagged risky for it, and every unchecked exercise, are
// left out. The faves tab shows only faves that are in that same filtered result, never a second, local check.
import { useCallback, useEffect, useState } from 'react'
import {
  fetchExercises,
  fetchQuizQuestions,
  MUSCLE_GROUP_LABELS,
  WORKOUT_GROUP_LABELS,
  type ExerciseFilters,
  type QuizQuestion,
  type Exercise,
} from '../api'
import DemoMedia from '../components/DemoMedia'
import ExerciseDetail from '../components/ExerciseDetail'
import FavoriteButton from '../components/FavoriteButton'
import Link from '../components/Link'
import QuestionField from '../components/QuestionField'
import { useEquipmentOptions } from '../equipment'
import { useFavorites, type Favorites } from '../favorites'
import { injuryStatusLabel } from '../injurySafety'

function label(value: string): string {
  return value.replace(/_/g, ' ')
}

const NO_FILTERS: ExerciseFilters = { group: '', avoid: [], equipment: [] }

const FOCUS_QUESTION: QuizQuestion = {
  id: 'library_focus',
  prompt: 'What do you want to work on?',
  type: 'single_select',
  required: false,
  options: [
    { value: 'all', label: 'Everything' },
    { value: 'upper', label: 'Upper body', description: 'Chest, back, shoulders and arms' },
    { value: 'lower', label: 'Lower body', description: 'Legs and glutes' },
    { value: 'mobility_core', label: 'Core / mobility', description: 'Core work, stretches and mobility' },
  ],
}

/** The quiz's own injury question, reworded for the library (same areas, same labels; "None" isn't a choice). */
function avoidQuestion(questions: QuizQuestion[]): QuizQuestion | null {
  const injuries = questions.find((q) => q.id === 'injuries')
  if (!injuries) return null
  return {
    id: 'library_avoid',
    prompt: 'Any areas to avoid because of an injury?',
    help_text:
      'We leave out every exercise tagged as risky for those areas, and every exercise nobody has checked for ' +
      'injuries yet: unchecked never means safe. The tags are drafts a physical therapist hasn’t reviewed.',
    type: 'multi_select',
    required: false,
    options: injuries.options.filter((o) => o.value !== injuries.exclusive),
  }
}

function ChipFilter<T extends string>({
  legend,
  options,
  selected,
  onChange,
}: {
  legend: string
  options: { value: T; label: string }[]
  selected: T[]
  onChange: (next: T[]) => void
}) {
  return (
    <fieldset className="filter-group">
      <legend>{legend}</legend>
      <div className="chip-row">
        {options.map((o) => {
          const on = selected.includes(o.value)
          return (
            <label key={o.value} className={`chip-check${on ? ' chip-on' : ''}`}>
              <input
                type="checkbox"
                checked={on}
                onChange={(e) => onChange(e.target.checked ? [...selected, o.value] : selected.filter((v) => v !== o.value))}
              />
              {o.label}
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}

function ExerciseCard({ ex, favorites, onOpen }: { ex: Exercise; favorites: Favorites; onOpen: () => void }) {
  return (
    <article className={`card group-${ex.muscle_group}`}>
      <DemoMedia url={ex.demo_media_url} type={ex.media_type} alt={`${ex.name} demo`} compact />
      <div className="card-body">
        <h3>
          {/* The button's ::after stretches over the whole card, so clicking anywhere opens the detail view. */}
          <button type="button" className="card-open" onClick={onOpen}>
            {ex.name}
          </button>
        </h3>
        <p>
          <strong>Works:</strong>{' '}
          {ex.workout_groups.map((g) => WORKOUT_GROUP_LABELS[g]).join(' and ')} ({MUSCLE_GROUP_LABELS[ex.muscle_group]})
        </p>
        <p>
          <strong>Equipment:</strong> {ex.equipment_needed.map(label).join(', ')}
        </p>
        <p>
          <strong>Level:</strong> {ex.difficulty}
        </p>
        <p className="injury-status">{injuryStatusLabel(ex)}</p>
        <span className={`badge badge-${ex.source_dataset}`}>{ex.source_dataset}</span>
      </div>
      <FavoriteButton
        name={ex.name}
        favorited={favorites.isFavorite(ex.id)}
        pending={favorites.isPending(ex.id)}
        onToggle={() => favorites.toggle(ex)}
      />
    </article>
  )
}

export default function ExercisesPage({ initialTab = 'all' }: { initialTab?: 'all' | 'faves' }) {
  const favorites = useFavorites()
  const [tab, setTabState] = useState<'all' | 'faves'>(initialTab)
  const equipmentOptions = useEquipmentOptions()
  // My Faves is a subtab of the library; the address follows it so /faves still links straight to it.
  function setTab(next: 'all' | 'faves') {
    setTabState(next)
    window.history.replaceState({}, '', next === 'faves' ? '/faves' : '/exercises')
  }
  const [filters, setFilters] = useState<ExerciseFilters>(NO_FILTERS)
  const [exercises, setExercises] = useState<Exercise[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const closeDetail = useCallback(() => setOpenId(null), [])
  const [avoidQ, setAvoidQ] = useState<QuizQuestion | null>(null)

  useEffect(() => {
    fetchQuizQuestions()
      .then((qs) => setAvoidQ(avoidQuestion(qs)))
      .catch(() => setAvoidQ(null))
  }, [])

  // The API does the filtering (real query params), so we never download and sift the whole library.
  useEffect(() => {
    let cancelled = false
    fetchExercises(filters)
      .then((data) => {
        if (!cancelled) {
          setExercises(data)
          setError(null)
        }
      })
      .catch((e: Error) => !cancelled && setError(e.message))
      .finally(() => !cancelled && setLoading(false))
    return () => {
      cancelled = true
    }
  }, [filters])

  function update(change: Partial<ExerciseFilters>) {
    setLoading(true)
    setFilters((f) => ({ ...f, ...change }))
  }

  const filtering = !!filters.group || !!filters.avoid.length || !!filters.equipment.length
  // Faves: only the ones in the API's filtered result (one implementation of the filters, incl. the injury one).
  const allowed = new Set(exercises.map((e) => e.id))
  const shown = tab === 'all' ? exercises : favorites.favorites.filter((f) => !filtering || allowed.has(f.id))

  const perSource = shown.reduce<Record<string, number>>((acc, ex) => {
    acc[ex.source_dataset] = (acc[ex.source_dataset] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <h2 className="page-title">Exercise Library</h2>

      <div className="tabs" role="group" aria-label="Exercise view">
        <button type="button" className={tab === 'all' ? 'tab tab-on' : 'tab'} aria-pressed={tab === 'all'} onClick={() => setTab('all')}>
          All Exercises
        </button>
        <button type="button" className={tab === 'faves' ? 'tab tab-on' : 'tab'} aria-pressed={tab === 'faves'} onClick={() => setTab('faves')}>
          My Faves ({favorites.favorites.length})
        </button>
      </div>

      <div className="filters library-questions">
        <QuestionField
          q={FOCUS_QUESTION}
          value={filters.group || 'all'}
          onChange={(v) => update({ group: v === 'all' ? '' : (v as ExerciseFilters['group']) })}
        />
        {avoidQ && (
          <QuestionField q={avoidQ} value={filters.avoid} onChange={(v) => update({ avoid: v as string[] })} />
        )}
        <ChipFilter
          legend="Equipment it uses"
          options={(equipmentOptions ?? []).map((o) => ({ value: o.value, label: o.label }))}
          selected={filters.equipment}
          onChange={(equipment) => update({ equipment })}
        />
        {filtering && (
          <button type="button" className="btn-ghost" onClick={() => update(NO_FILTERS)}>
            Clear filters
          </button>
        )}
        <span className="count" aria-live="polite">
          {tab === 'all' && loading
            ? 'Loading…'
            : `${shown.length} ${tab === 'faves' ? 'faves' : 'exercises'}${
                shown.length ? ` (${Object.entries(perSource).map(([src, n]) => `${n} ${src}`).join(', ')})` : ''
              }`}
        </span>
      </div>

      {favorites.needsSignIn && (
        <p className="notice">
          Sign in to save favorites: <Link to="/settings">sign in</Link> or <Link to="/quiz">create an account</Link>.
        </p>
      )}
      {favorites.error && <p className="error">{favorites.error}</p>}
      {error && <p className="error">Couldn't load data: {error}. Is the backend running on port 8000?</p>}

      {tab === 'faves' && !favorites.signedIn && (
        <p>
          Sign in to see your faves: <Link to="/settings">sign in</Link> or <Link to="/quiz">create an account</Link>.
        </p>
      )}
      {tab === 'faves' && favorites.signedIn && favorites.loaded && favorites.favorites.length === 0 && (
        <p>No faves yet. Tap the heart on any exercise to save it here.</p>
      )}
      {!loading && !error && shown.length === 0 && filtering && (tab === 'all' || favorites.favorites.length > 0) && (
        <p>No exercises match these filters.</p>
      )}

      <section className="grid">
        {shown.map((ex) => (
          <ExerciseCard key={ex.id} ex={ex} favorites={favorites} onOpen={() => setOpenId(ex.id)} />
        ))}
      </section>

      {openId && <ExerciseDetail key={openId} exerciseId={openId} favorites={favorites} onClose={closeDetail} />}
    </>
  )
}
