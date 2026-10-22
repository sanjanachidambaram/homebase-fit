import { useCallback, useEffect, useState } from 'react'
import { fetchExercises, MUSCLE_GROUP_LABELS, type Exercise, type MuscleGroup } from '../api'
import DemoMedia from '../components/DemoMedia'
import ExerciseDetail from '../components/ExerciseDetail'
import FavoriteButton from '../components/FavoriteButton'
import Link from '../components/Link'
import { useFavorites, type Favorites } from '../favorites'

function label(value: string): string {
  return value.replace(/_/g, ' ')
}

function ExerciseCard({ ex, favorites, onOpen }: { ex: Exercise; favorites: Favorites; onOpen: () => void }) {
  return (
    <article className="card">
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

export default function ExercisesPage() {
  const favorites = useFavorites()
  const [tab, setTab] = useState<'all' | 'faves'>('all')
  const [group, setGroup] = useState<MuscleGroup | ''>('')
  const [exercises, setExercises] = useState<Exercise[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [openId, setOpenId] = useState<string | null>(null)
  const closeDetail = useCallback(() => setOpenId(null), [])

  useEffect(() => {
    let cancelled = false
    fetchExercises(group)
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
  }, [group])

  const shown =
    tab === 'all' ? exercises : favorites.favorites.filter((f) => group === '' || f.muscle_group === group)

  const perSource = shown.reduce<Record<string, number>>((acc, ex) => {
    acc[ex.source_dataset] = (acc[ex.source_dataset] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <h2 className="page-title">Exercise library (test page)</h2>

      <div className="tabs" role="group" aria-label="Exercise view">
        <button type="button" className={tab === 'all' ? 'tab tab-on' : 'tab'} aria-pressed={tab === 'all'} onClick={() => setTab('all')}>
          All exercises
        </button>
        <button type="button" className={tab === 'faves' ? 'tab tab-on' : 'tab'} aria-pressed={tab === 'faves'} onClick={() => setTab('faves')}>
          My Faves ({favorites.favorites.length})
        </button>
      </div>

      <div className="controls">
        <label htmlFor="group">Muscle group</label>
        <select
          id="group"
          value={group}
          onChange={(e) => {
            setLoading(true)
            setGroup(e.target.value as MuscleGroup | '')
          }}
        >
          <option value="">All</option>
          {Object.entries(MUSCLE_GROUP_LABELS).map(([value, text]) => (
            <option key={value} value={value}>
              {text}
            </option>
          ))}
        </select>
        <span className="count">
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
      {tab === 'faves' && favorites.signedIn && favorites.loaded && shown.length === 0 && (
        <p>No faves yet. Tap the heart on any exercise to save it here.</p>
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
