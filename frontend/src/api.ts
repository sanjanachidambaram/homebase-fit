// Types and fetch helpers for the FastAPI backend (proxied at /api in dev).

export type MuscleGroup = 'legs' | 'arms' | 'chest' | 'shoulders' | 'back' | 'core' | 'full_body'

export const MUSCLE_GROUP_LABELS: Record<MuscleGroup, string> = {
  legs: 'Legs',
  arms: 'Arms',
  chest: 'Chest',
  shoulders: 'Shoulders',
  back: 'Back',
  core: 'Core',
  full_body: 'Full body',
}

export interface Citation {
  claim: string
  source: string
}

export interface ReviewFields {
  status: 'placeholder' | 'pt_reviewed'
  review_notice: string | null // "Content pending expert review" while status is placeholder
  citations: Citation[]
}

export type MediaType = 'image' | 'gif' | 'video'

export interface Exercise extends ReviewFields {
  id: string
  name: string
  muscle_group: MuscleGroup
  equipment_needed: string[]
  difficulty: 'beginner' | 'intermediate' | 'advanced'
  category: string | null
  primary_muscles: string[]
  secondary_muscles: string[]
  injury_contraindications: string[]
  contraindication_status: 'untagged' | 'draft' | 'pt_reviewed'
  est_time_seconds: number
  instructions: string // steps separated by newlines
  demo_media_url: string | null // null until the file exists
  media_type: MediaType | null // how to render demo_media_url
  source_dataset: string
  source: { name: string; url: string | null; license: string; status: 'active' | 'placeholder' | 'pending' }
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

export const fetchExercise = (id: string) => getJson<Exercise>(`/api/exercises/${encodeURIComponent(id)}`)

export function fetchSources(): Promise<Source[]> {
  return getJson<Source[]>('/api/sources')
}

// ---------------------------------------------------------------- reviewed content

export interface Program extends ReviewFields {
  source_id: string
  id: number
  name: string
  goal_tags: string[]
  injury_focus: string[]
  description: string
  science_rationale: string
}

export interface Article extends ReviewFields {
  source_id: string
  slug: string
  title: string
  category: string
  content: string
  media_url: string | null
}

export const fetchPrograms = () => getJson<Program[]>('/api/programs')
export const fetchArticles = () => getJson<Article[]>('/api/basics')

// ---------------------------------------------------------------- accounts and quiz

export interface QuizQuestion {
  id: string
  prompt: string
  type: 'multi_select' | 'single_select' | 'number' | 'text'
  options: { value: string; label: string }[]
  required: boolean
  health?: boolean
  exclusive?: string
  allow_free_text?: boolean
  free_text_prompt?: string
  unit?: string
  min?: number
  max?: number
}

export interface QuizProfile {
  goals: string[]
  timeline: string | null
  injury_flags: string[]
  injury_notes: string | null
  age: number | null
  weight: number | null
  height: number | null
  consent_accepted: boolean
  consent_accepted_at: string
  consent_version: string
  updated_at: string
}

export interface Account {
  id: number
  email: string
  created_at: string
  quiz_profile: QuizProfile | null
}

export interface AuthResult {
  user_id: number
  token: string
}

/** fetch + JSON with the API's error message ("detail") surfaced as the Error text. */
async function request<T>(path: string, init: RequestInit = {}, token?: string): Promise<T> {
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(path, { ...init, headers })
  const body = await res.json().catch(() => null)
  if (!res.ok) {
    const detail = body?.detail
    const message = typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : null
    throw new Error(message ?? `Request failed (${res.status})`)
  }
  return body as T
}

export const signUp = (email: string, password: string) =>
  request<AuthResult>('/api/users', { method: 'POST', body: JSON.stringify({ email, password }) })

export const logIn = (email: string, password: string) =>
  request<AuthResult>('/api/login', { method: 'POST', body: JSON.stringify({ email, password }) })

export const fetchQuizQuestions = () => request<QuizQuestion[]>('/api/quiz/questions')

export const fetchAccount = (userId: number, token: string) => request<Account>(`/api/users/${userId}`, {}, token)

export function submitQuiz(
  userId: number,
  token: string,
  body: { consent_accepted: boolean; consent_version: string; answers: Record<string, unknown>; injury_notes?: string },
) {
  return request<QuizProfile>(`/api/users/${userId}/quiz-profile`, { method: 'PUT', body: JSON.stringify(body) }, token)
}

export const deleteAccount = (userId: number, token: string) =>
  request<{ deleted: boolean; rows_removed: Record<string, number> }>(`/api/users/${userId}`, { method: 'DELETE' }, token)

// ---------------------------------------------------------------- favorites

export const fetchFavorites = (token: string) => request<Exercise[]>('/api/favorites', {}, token)

export const addFavorite = (exerciseId: string, token: string) =>
  request<{ favorited: boolean }>('/api/favorites', { method: 'POST', body: JSON.stringify({ exercise_id: exerciseId }) }, token)

export const removeFavorite = (exerciseId: string, token: string) =>
  request<{ favorited: boolean }>(`/api/favorites/${encodeURIComponent(exerciseId)}`, { method: 'DELETE' }, token)
