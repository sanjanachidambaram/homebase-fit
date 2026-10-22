import { useEffect, useState } from 'react'
import { fetchExercises, MUSCLE_GROUP_LABELS, type Exercise, type MuscleGroup } from '../api'

function label(value: string): string {
  return value.replace(/_/g, ' ')
}

function ExerciseCard({ ex }: { ex: Exercise }) {
  return (
    <article className="card">
      {ex.demo_image_url ? (
        <img src={ex.demo_image_url} alt={`${ex.name} demo`} loading="lazy" />
      ) : (
        <div className="no-media">No demo yet</div>
      )}
      <div className="card-body">
        <h3>{ex.name}</h3>
        <p>
          <strong>Muscle group:</strong> {MUSCLE_GROUP_LABELS[ex.muscle_group]}
        </p>
        <p>
          <strong>Equipment:</strong> {ex.equipment_needed.map(label).join(', ')}
        </p>
        <span className={`badge badge-${ex.source_dataset}`}>{ex.source_dataset}</span>
      </div>
    </article>
  )
}

export default function ExercisesPage() {
  const [group, setGroup] = useState<MuscleGroup | ''>('')
  const [exercises, setExercises] = useState<Exercise[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

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

  const perSource = exercises.reduce<Record<string, number>>((acc, ex) => {
    acc[ex.source_dataset] = (acc[ex.source_dataset] ?? 0) + 1
    return acc
  }, {})

  return (
    <>
      <h2 className="page-title">Exercise library (test page)</h2>
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
          {loading
            ? 'Loading…'
            : `${exercises.length} exercises (${Object.entries(perSource)
                .map(([src, n]) => `${n} ${src}`)
                .join(', ')})`}
        </span>
      </div>

      {error && <p className="error">Couldn't load data: {error}. Is the backend running on port 8000?</p>}

      <section className="grid">
        {exercises.map((ex) => (
          <ExerciseCard key={ex.id} ex={ex} />
        ))}
      </section>
    </>
  )
}
