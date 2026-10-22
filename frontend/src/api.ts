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

/** Why an exercise carries an injury tag. tier is ai_drafted until a licensed PT reviews it. Never a citation. */
export interface InjuryRationale {
  reasoning: string
  tier: 'ai_drafted' | 'pt_reviewed'
  source: string // "Pending review by a licensed physical therapist", or the reviewing PT
}

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
  injury_rationale: Partial<Record<string, InjuryRationale>> // one per injury_contraindications entry
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

/** Library filters. Each list is "any of these"; different filters must all match. Done by the API, in SQL. */
export interface ExerciseFilters {
  muscleGroup: MuscleGroup | ''
  equipment: string[] // exercises that USE any of these; 'none' = bodyweight
  difficulty: Exercise['difficulty'][]
  injuryStatus: Exercise['contraindication_status'][]
}

export function exerciseQuery(f: ExerciseFilters): string {
  const q = new URLSearchParams()
  if (f.muscleGroup) q.set('muscle_group', f.muscleGroup)
  f.equipment.forEach((v) => q.append('equipment', v))
  f.difficulty.forEach((v) => q.append('difficulty', v))
  f.injuryStatus.forEach((v) => q.append('injury_status', v))
  const s = q.toString()
  return s ? `?${s}` : ''
}

export function fetchExercises(filters: ExerciseFilters): Promise<Exercise[]> {
  return getJson<Exercise[]>(`/api/exercises${exerciseQuery(filters)}`)
}

export const fetchExercise = (id: string) => getJson<Exercise>(`/api/exercises/${encodeURIComponent(id)}`)

export function fetchSources(): Promise<Source[]> {
  return getJson<Source[]>('/api/sources')
}

// ---------------------------------------------------------------- reviewed content

export interface Article extends ReviewFields {
  source_id: string
  slug: string
  title: string
  category: string
  content: string
  media_url: string | null
}

export const fetchArticles = () => getJson<Article[]>('/api/basics')

// ---------------------------------------------------------------- accounts and quiz

export interface QuizQuestion {
  id: string
  prompt: string
  type: 'multi_select' | 'single_select' | 'number' | 'text' | 'date'
  options: { value: string; label: string; description?: string }[]
  required: boolean
  help_text?: string
  health?: boolean
  exclusive?: string
  allow_free_text?: boolean
  free_text_prompt?: string
  unit?: string
  min?: number
  max?: number
  /** goal_weight: gentle note when the goal implies losing faster than max_lbs_per_week (never a block) */
  rate_note?: { max_lbs_per_week: number; text: string; source: string }
}

export interface QuizProfile {
  goals: string[]
  timeline: string | null
  injury_flags: string[]
  injury_notes: string | null
  age: number | null
  weight: number | null
  height: number | null
  experience_level: string | null
  days_available: number | null
  session_length_minutes: number | null
  equipment: string[]
  other_activity_days: number
  other_activity_notes: string | null
  goal_weight: number | null
  goal_date: string | null
  pregnancy_status: string | null
  needs_clinical_review: boolean
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

/** An API error. `code` and `page` are set when the server says where to send the user instead
 *  (e.g. code "needs_clinical_review", page "/pregnancy-support"). */
export class ApiError extends Error {
  status: number
  code?: string
  page?: string
  constructor(message: string, status: number, code?: string, page?: string) {
    super(message)
    this.status = status
    this.code = code
    this.page = page
  }
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
    const message =
      typeof detail === 'string' ? detail : Array.isArray(detail) ? detail[0]?.msg : detail?.message ?? null
    throw new ApiError(message ?? `Request failed (${res.status})`, res.status, detail?.code, detail?.page)
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

// ---------------------------------------------------------------- agents (all need a sign-in)

export interface AgentMeta {
  agent_run_id?: number
  usage?: { input_tokens: number; output_tokens: number; cached_tokens: number; requests: number; tool_calls: number }
  tool_calls?: { tool: string; args: Record<string, unknown>; called_by: string }[]
  agent_called?: boolean
}

export interface AgentResponse<T> {
  result: T
  meta: AgentMeta
}

// The weekly plan is generated by code (backend/app/services/program_generator.py), not by the AI.
export interface PlanExercise {
  exercise_id: string
  name: string
  muscle_group: MuscleGroup
  sets: string
  reps: string
  rest_seconds: number
  est_minutes: number
  injury_check: string
}

export interface PlanDay {
  day: 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
  kind: 'training' | 'rest'
  focus: string | null
  exercises: PlanExercise[]
  est_minutes: number
}

export interface WeeklyProgram {
  generated: boolean
  blocked_reason: string | null
  needs_clinical_review: boolean
  goals: string[]
  experience_level: string
  training_days: number
  days: PlanDay[]
  protocol: {
    goals_used: string[]
    split_type: string
    sessions_per_week: number
    session_length_minutes: number
    sets_range: string
    reps_range: string
    rest_seconds: number
    progression_notes: string[]
    blending_rules_applied: string[]
    status: 'placeholder' | 'pt_reviewed'
    review_notice: string | null
    citations: Citation[]
  } | null
  safety: {
    injury_flags: string[]
    checked_only: boolean
    excluded_as_contraindicated: number
    equipment: string[] | null
    // Which exercises the injury filter left out, and the (AI-drafted until PT-reviewed) reason for each.
    left_out_for_injury: {
      exercise_id: string
      name: string
      muscle_group: MuscleGroup
      cautions: ({ injury: string } & Partial<InjuryRationale>)[]
    }[]
  } | null
  notes: string[]
}

export interface PlanRecommendation {
  plan: WeeklyProgram
  explanation: string
  review_note: string | null
}

export const fetchPlan = (token: string) => request<WeeklyProgram>('/api/plan', {}, token)

export interface WorkoutRequest {
  picks: Partial<Record<MuscleGroup, number>>
  time_budget_minutes: number
  equipment?: string[]
}

export interface SessionExercise {
  order: number
  exercise_id: string
  name: string
  muscle_group: MuscleGroup
  sets: number
  reps: string
  rest_seconds: number
  est_minutes: number
  injury_check: string
}

export interface WorkoutSession {
  exercises: SessionExercise[]
  total_estimated_minutes: number
  time_budget_minutes: number
  balance_note: string
  notes: string[]
}

export type GoalStatus = 'on_track' | 'ahead' | 'behind' | 'insufficient_data'

export interface CoachMessage {
  encouragement: string
  fun_fact: string | null
  goal_status: GoalStatus
  overtraining_flag: boolean
  rest_suggestion: string | null
  current_streak_days: number
  sessions_last_30_days: number
  total_weight_lifted_lbs: number
}

export interface BasicsAnswer {
  answer: string
  answered: boolean
  redirected_to_professional: boolean
  sources: { slug: string; title: string; status: string; review_notice: string | null; citations: Citation[] }[]
  review_note: string | null
}

export const recommendProgram = (token: string) =>
  request<AgentResponse<PlanRecommendation>>('/api/programs/recommend', { method: 'POST' }, token)

export const buildWorkout = (token: string, body: WorkoutRequest) =>
  request<AgentResponse<WorkoutSession>>('/api/workouts/build', { method: 'POST', body: JSON.stringify(body) }, token)

export const fetchCoach = (token: string) => request<AgentResponse<CoachMessage>>('/api/coach/summary', {}, token)

export const askBasics = (token: string, question: string) =>
  request<AgentResponse<BasicsAnswer>>('/api/basics/ask', { method: 'POST', body: JSON.stringify({ question }) }, token)

// ---------------------------------------------------------------- the public "How We Build Your Plan" example

export interface PlanExample {
  profile: {
    age: number
    goals: string[]
    experience_level: string
    injury_flags: string[]
    equipment: string[]
    days_available: number
    session_length_minutes: number
  }
  funnel: { step: string; exercises_left: number; removed: number }[]
  plan: WeeklyProgram
}

/** A live run of the real generator for a fixed profile (public, no sign-in, no AI). */
export const fetchPlanExample = () => getJson<PlanExample>('/api/plan/example')
