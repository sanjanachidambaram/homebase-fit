// Types and fetch helpers for the FastAPI backend (proxied at /api in dev).

export type MuscleGroup = 'legs' | 'arms' | 'back' | 'core' | 'full_body'

export const MUSCLE_GROUP_LABELS: Record<MuscleGroup, string> = {
  legs: 'Legs',
  arms: 'Arms, chest & shoulders',
  back: 'Back',
  core: 'Core',
  full_body: 'Full body',
}

export interface Exercise {
  id: string
  name: string
  muscle_group: MuscleGroup
  equipment_needed: string[]
  difficulty: 'beginner' | 'intermediate' | 'advanced'
  category: string | null
  primary_muscles: string[]
  injury_contraindications: string[]
  contraindication_status: 'untagged' | 'draft' | 'pt_reviewed'
  est_time_seconds: number
  instructions: string
  demo_image_url: string | null
  source_dataset: string
}

export interface Source {
  id: string
  name: string
  url: string | null
  license: string
  used_for: string
  status: 'active' | 'placeholder' | 'pending'
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(path)
  if (!res.ok) throw new Error(`${path} returned ${res.status}`)
  return res.json() as Promise<T>
}

export function fetchExercises(muscleGroup: MuscleGroup | ''): Promise<Exercise[]> {
  const query = muscleGroup ? `?muscle_group=${muscleGroup}` : ''
  return getJson<Exercise[]>(`/api/exercises${query}`)
}

export function fetchSources(): Promise<Source[]> {
  return getJson<Source[]>('/api/sources')
}
