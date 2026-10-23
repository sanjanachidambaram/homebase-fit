import { useCallback, useEffect, useState } from 'react'
import {
  fetchExercises,
  MUSCLE_GROUP_LABELS,
  type Exercise,
  type ExerciseFilters,
  type MuscleGroup,
} from '../api'
import DemoMedia from '../components/DemoMedia'
import ExerciseDetail from '../components/ExerciseDetail'
import FavoriteButton from '../components/FavoriteButton'
import Link from '../components/Link'
import { useEquipmentOptions } from '../equipment'
import { useFavorites, type Favorites } from '../favorites'
import { INJURY_STATUS_OPTIONS, injuryStatusLabel } from '../injurySafety'

function label(value: string): string {
  return value.replace(/_/g, ' ')
}

const LEVEL_OPTIONS: { value: Exercise['difficulty']; label: string }[] = [
  { value: 'beginner', label: 'Beginner' },
  { value: 'intermediate', label: 'Intermediate' },
  { value: 'advanced', label: 'Advanced' },
]
const NO_FILTERS: ExerciseFilters = { muscleGroup: '', equipment: [], difficulty: [], injuryStatus: [] }

/** Same rules as the API, for the (small, already-loaded) faves list. */
function matches(ex: Exercise, f: ExerciseFilters): boolean {
  return (
    (!f.muscleGroup || ex.muscle_group === f.muscleGroup) &&
    (!f.equipment.length || ex.equipment_needed.some((e) => f.equipment.includes(e))) &&
    (!f.difficulty.length || f.difficulty.includes(ex.difficulty)) &&
    (!f.injuryStatus.length || f.injuryStatus.includes(ex.contraindication_status))
  )
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
          <strong>Muscle group:</strong> {MUSCLE_GROUP_LABELS[ex.muscle_group]}
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

  const filtering =
    !!filters.muscleGroup || !!filters.equipment.length || !!filters.difficulty.length || !!filters.injuryStatus.length
  const shown = tab === 'all' ? exercises : favorites.favorites.filter((f) => matches(f, filters))

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

      <div className="filters">
        <div className="controls">
          <label htmlFor="group">Muscle group</label>
          <select
            id="group"
            value={filters.muscleGroup}
            onChange={(e) => update({ muscleGroup: e.target.value as MuscleGroup | '' })}
          >
            <option value="">All</option>
            {Object.entries(MUSCLE_GROUP_LABELS).map(([value, text]) => (
              <option key={value} value={value}>
                {text}
              </option>
            ))}
          </select>
          {filtering && (
            <button type="button" className="btn-ghost" onClick={() => update(NO_FILTERS)}>
              Clear filters
            </button>
          )}
        </div>
        <ChipFilter
          legend="Equipment it uses"
          options={(equipmentOptions ?? []).map((o) => ({ value: o.value, label: o.label }))}
          selected={filters.equipment}
          onChange={(equipment) => update({ equipment })}
        />
        <ChipFilter
          legend="Level"
          options={LEVEL_OPTIONS}
          selected={filters.difficulty}
          onChange={(difficulty) => update({ difficulty })}
        />
        <ChipFilter
          legend="Injury safety"
          options={INJURY_STATUS_OPTIONS}
          selected={filters.injuryStatus}
          onChange={(injuryStatus) => update({ injuryStatus })}
        />
        <p className="hint">
          Injury cautions are drafts that a physical therapist hasn't reviewed yet, and "not checked" means nobody has
          looked, not that an exercise is safe.
        </p>
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
        <p>
          No exercises match these filters
          {filters.injuryStatus.length === 1 && filters.injuryStatus[0] === 'pt_reviewed'
            ? ' (no exercise has been PT-reviewed yet)'
            : ''}
          .
        </p>
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
