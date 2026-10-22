import { useEffect, useRef, useState } from 'react'
import { fetchExercise, MUSCLE_GROUP_LABELS, type Exercise } from '../api'
import type { Favorites } from '../favorites'
import DemoMedia from './DemoMedia'
import FavoriteButton from './FavoriteButton'
import ReviewInfo from './ReviewInfo'

const words = (values: string[]) => values.map((v) => v.replace(/_/g, ' ')).join(', ')

function injuryNote(ex: Exercise): string {
  const avoid = ex.injury_contraindications.length ? words(ex.injury_contraindications) : null
  if (ex.contraindication_status === 'untagged') return 'Not yet checked for injury safety. Ask a doctor or physical therapist if you have an injury.'
  if (ex.contraindication_status === 'draft') {
    return (avoid ? `Drafted advice: avoid with ${avoid}.` : 'No injury cautions drafted.') + ' Not yet reviewed by a physical therapist.'
  }
  return avoid ? `Avoid with ${avoid}.` : 'No injury cautions.'
}

/** Full exercise info in a modal. Closes on Escape, the Close button, or a click outside. */
export default function ExerciseDetail({
  exerciseId,
  favorites,
  onClose,
}: {
  exerciseId: string
  favorites: Favorites
  onClose: () => void
}) {
  const [exercise, setExercise] = useState<Exercise | null>(null)
  const [error, setError] = useState<string | null>(null)
  const closeRef = useRef<HTMLButtonElement>(null)

  useEffect(() => {
    let cancelled = false
    fetchExercise(exerciseId)
      .then((ex) => !cancelled && setExercise(ex))
      .catch((e: Error) => !cancelled && setError(e.message))
    return () => {
      cancelled = true
    }
  }, [exerciseId])

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
      <div
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-labelledby="exercise-detail-title"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="modal-head">
          <h2 id="exercise-detail-title">{exercise?.name ?? 'Exercise'}</h2>
          <button ref={closeRef} type="button" className="btn-secondary" onClick={onClose}>
            Close
          </button>
        </div>

        {error && <p className="error">Couldn't load this exercise: {error}</p>}
        {!exercise && !error && <p>Loading…</p>}

        {exercise && (
          <>
            <div className="detail-media">
              <DemoMedia url={exercise.demo_media_url} type={exercise.media_type} alt={`${exercise.name} demo`} />
            </div>

            <FavoriteButton
              name={exercise.name}
              withLabel
              favorited={favorites.isFavorite(exercise.id)}
              pending={favorites.isPending(exercise.id)}
              onToggle={() => favorites.toggle(exercise)}
            />
            {favorites.needsSignIn && <p className="hint">Sign in (Settings) to save favorites.</p>}
            {favorites.error && <p className="error">{favorites.error}</p>}

            <dl className="facts">
              <dt>Muscle group</dt>
              <dd>{MUSCLE_GROUP_LABELS[exercise.muscle_group]}</dd>
              {exercise.primary_muscles.length > 0 && (
                <>
                  <dt>Main muscles</dt>
                  <dd>{words(exercise.primary_muscles)}</dd>
                </>
              )}
              {exercise.secondary_muscles.length > 0 && (
                <>
                  <dt>Also works</dt>
                  <dd>{words(exercise.secondary_muscles)}</dd>
                </>
              )}
              <dt>Equipment</dt>
              <dd>{words(exercise.equipment_needed)}</dd>
              <dt>Level</dt>
              <dd>{exercise.difficulty}</dd>
              <dt>Injury safety</dt>
              <dd>{injuryNote(exercise)}</dd>
            </dl>

            <h3>How to do it</h3>
            <ol className="steps-list">
              {exercise.instructions
                .split('\n')
                .filter((step) => step.trim())
                .map((step) => (
                  <li key={step}>{step}</li>
                ))}
            </ol>

            <h3>Source</h3>
            <p>
              {exercise.source.url ? (
                <a href={exercise.source.url} target="_blank" rel="noopener noreferrer">
                  {exercise.source.name}
                </a>
              ) : (
                exercise.source.name
              )}{' '}
              · {exercise.source.license}
            </p>
            <ReviewInfo item={exercise} />
          </>
        )}
      </div>
    </div>
  )
}
