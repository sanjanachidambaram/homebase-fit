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
  workout_groups: WorkoutGroup[] // which of the plans' groups it counts toward (full-body lifts: upper and lower)
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

/** Library filters, read like the quiz: a workout group to focus on, and body areas to avoid because of an injury.
 *  The API does all of it; `avoid` runs through the same safety search as the plan generator (tagged-risky and
 *  untagged exercises both left out). Equipment is "any of these"; different filters must all match. */
export interface ExerciseFilters {
  group: Exclude<WorkoutGroup, 'cardio'> | ''
  avoid: string[] // the quiz's injury flags (shoulder, knee, ...)
  equipment: string[] // exercises that USE any of these; 'none' = bodyweight
}

export function exerciseQuery(f: ExerciseFilters): string {
  const q = new URLSearchParams()
  if (f.group) q.set('group', f.group)
  f.avoid.forEach((v) => q.append('avoid', v))
  f.equipment.forEach((v) => q.append('equipment', v))
  const s = q.toString()
  return s ? `?${s}` : ''
}

export function fetchExercises(filters: ExerciseFilters): Promise<Exercise[]> {
  return getJson<Exercise[]>(`/api/exercises${exerciseQuery(filters)}`)
}

/** Every equipment value used by any exercise (GET /api/exercises/equipment), so pickers never drift from the data. */
export interface EquipmentOption {
  value: string
  label: string
  exercises: number
  always_included: boolean // bodyweight ("none"): always in, nothing to pick
}

export const fetchEquipment = () => getJson<EquipmentOption[]>('/api/exercises/equipment')

export const fetchExercise = (id: string) => getJson<Exercise>(`/api/exercises/${encodeURIComponent(id)}`)

/** Live counts for the About page (GET /api/data-summary), so its numbers never go stale. */
export interface DataSummary {
  exercises: {
    total: number
    by_source: { id: string; name: string; url: string | null; license: string; count: number }[]
    injury_checked: number // looked at for injuries (draft or PT-reviewed), even if it got no caution
    injury_unchecked: number
    injury_pt_reviewed: number
    with_cautions: number
    cautions: number
    reasons_ai_drafted: number
    reasons_pt_reviewed: number
  }
  protocols: { total: number; placeholder: number; with_citations: number }
}

export const fetchDataSummary = () => getJson<DataSummary>('/api/data-summary')

export function fetchSources(): Promise<Source[]> {
  return getJson<Source[]>('/api/sources')
}

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
  unit?: string
  min?: number
  max?: number
  /** multi_select: a value that's always on (bodyweight) */
  always_included?: string
  /** Only asked when another answer matches (weight, goal weight: only when the goal is losing weight) */
  ask_if?: { question: string; equals: string }
  /** goal_weight: a gentle, cited note on how long the change takes at a gradual pace (never a block) */
  pace_note?: { lbs_per_week: [number, number]; text: string; source: string }
}

export type Goal = 'stronger' | 'lose_weight' | 'feel_good'

export interface QuizProfile {
  goal: Goal
  injury_flags: string[]
  experience_level: string | null
  equipment: string[]
  weight: number | null // only on the losing-weight path
  goal_weight: number | null // only on the losing-weight path
  pregnancy_status: string | null
  needs_clinical_review: boolean
  consent_accepted: boolean
  consent_accepted_at: string
  consent_version: string
  updated_at: string
  calendar_mode: CalendarMode
  plan_reviewed: boolean
  plan_swaps: Record<string, string>
  plan_started_on: string | null
}

/** How the calendar is filled: the quiz plan, the quiz plan after a review pass, or open days you build yourself. */
export type CalendarMode = 'generated' | 'review' | 'self'

export interface Account {
  id: number
  username: string
  first_name: string | null // null for accounts made before names were asked for
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

/** Should this error sign the user out? Only when the server says the sign-in itself is no longer usable:
 *  401 (missing, bad or expired token) or 404 "Account not found." for your own account (it was deleted).
 *  Never for a server error (5xx), a backend that's restarting (502), a network failure, or any other
 *  message that happens to mention signing in. */
export function isSignInGone(e: unknown): boolean {
  return e instanceof ApiError && (e.status === 401 || (e.status === 404 && /account not found/i.test(e.message)))
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

export const signUp = (username: string, firstName: string, password: string) =>
  request<AuthResult>('/api/users', {
    method: 'POST',
    body: JSON.stringify({ username, first_name: firstName, password }),
  })

export const logIn = (username: string, password: string) =>
  request<AuthResult>('/api/login', { method: 'POST', body: JSON.stringify({ username, password }) })

export const fetchQuizQuestions = () => request<QuizQuestion[]>('/api/quiz/questions')

export const fetchAccount = (userId: number, token: string) => request<Account>(`/api/users/${userId}`, {}, token)

export function submitQuiz(
  userId: number,
  token: string,
  body: { consent_accepted: boolean; consent_version: string; answers: Record<string, unknown> },
) {
  return request<QuizProfile>(`/api/users/${userId}/quiz-profile`, { method: 'PUT', body: JSON.stringify(body) }, token)
}

/** "Reset my quiz": back to no plan, without retaking now. Completed days, notes, logs and favorites are kept. */
export const resetQuiz = (userId: number, token: string) =>
  request<{ reset: boolean; calendar_days_cleared: number }>(`/api/users/${userId}/quiz-profile`, { method: 'DELETE' }, token)

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
  category: PlanCategory
  slot: string
  reps_your_call: boolean // Getting stronger: how many reps is the person's own call
  weighted: boolean // uses dumbbells, kettlebells...: gets a weight field (bodyweight ones stay blank)
  load: 'arms' | 'legs' | null
  default_weight_lb: number | null
  swapped_from?: string | null // review mode: the generated exercise this replaced
}

/** The 4 workout groups days are built from. */
export type PlanCategory = 'upper' | 'lower' | 'mobility' | 'cardio'

export interface PlanDay {
  day: 'mon' | 'tue' | 'wed' | 'thu' | 'fri' | 'sat' | 'sun'
  kind: 'training' | 'rest'
  category: PlanCategory | null
  focus: string | null
  exercises: PlanExercise[]
  est_minutes: number
}

/** Suggested weights week by week from the defaults (shared_rules rule 8), before anything is logged. */
export interface WeightPlan {
  rule: string
  calibration: string
  defaults_lb: { arms: number; legs: number } | null // null = beginner: bodyweight only
  step_lb: { arms: number; legs: number }
  schedule_weeks: number
  schedule: { exercise_id: string; name: string; load: 'arms' | 'legs'; weeks: number[]; weight_lb: (number | null)[] }[]
}

/** Where a date sits in the 6-month plan (26 weeks from the day the quiz was saved). */
export interface PlanWindow {
  started_on: string
  ends_on: string
  weeks: number // 26
  current_week: number // today's week of the plan, 1-26
  ended: boolean // past the last day: retake the quiz for a new 6 months
}

export interface WeeklyProgram {
  swap_options?: Record<string, { id: string; name: string; injury_check: string }[]> | null
  generated: boolean
  blocked_reason: string | null
  needs_clinical_review: boolean
  goal: Goal
  goal_label: string
  experience_level: string
  training_days: number
  block_weeks: number // the pattern repeats every this many weeks
  plan_weeks: number // how long the plan runs: 26 weeks (6 months)
  window?: PlanWindow | null // GET /api/plan: where today sits in the 6 months
  weeks: { week_in_block: number; days: PlanDay[] }[]
  days: PlanDay[] // week 1
  weights: WeightPlan | null
  protocol: {
    goal: Goal
    experience_level: string
    session_length_minutes: number
    sets_range: string
    reps_range: string
    rest_seconds: number
    progression_note: string
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

export const recommendProgram = (token: string) =>
  request<AgentResponse<PlanRecommendation>>('/api/programs/recommend', { method: 'POST' }, token)

export const buildWorkout = (token: string, body: WorkoutRequest) =>
  request<AgentResponse<WorkoutSession> & { built_id: number }>(
    '/api/workouts/build',
    { method: 'POST', body: JSON.stringify(body) },
    token,
  )

export const fetchCoach = (token: string) => request<AgentResponse<CoachMessage>>('/api/coach/summary', {}, token)

// ---------------------------------------------------------------- the public "How We Build Your Plan" example

export interface PlanExample {
  profile: {
    goal: Goal
    experience_level: string
    injury_flags: string[]
    equipment: string[]
  }
  funnel: { step: string; exercises_left: number; removed: number }[]
  plan: WeeklyProgram
}

/** A live run of the real generator for a fixed profile (public, no sign-in, no AI). */
export const fetchPlanExample = () => getJson<PlanExample>('/api/plan/example')

// ---------------------------------------------------------------- calendar

export interface CalendarExercise {
  exercise_id: string
  name: string
  muscle_group: MuscleGroup
  sets: string
  reps: string
  rest_seconds: number
  est_minutes: number
  injury_check: string
  reps_your_call?: boolean // Getting stronger: reps are the person's own call
  weighted?: boolean
  load?: 'arms' | 'legs' | null
  default_weight_lb?: number | null
}

export interface CalendarEntry {
  id: number
  date: string // YYYY-MM-DD
  weekday: PlanDay['day']
  day_type: 'workout' | 'rest' | 'cardio' // cardio: "Add cardio" (done once cardio is logged on its date)
  // A snapshot of that day of the plan, taken when the entry was made (it never changes by itself).
  workout: {
    plan_day: PlanDay['day']
    focus: string | null
    est_minutes: number
    exercises: CalendarExercise[]
    protocol_status: 'placeholder' | 'pt_reviewed' | null
    review_notice: string | null
    notes?: string[] // custom days: the Workout Builder's notes (e.g. fewer moves fit your filters)
    open?: boolean // nothing planned: "I'll build it myself" mode, or a day opened by "Save to calendar"
    week?: number // week of the plan
    week_in_block?: number // which week of the repeating 2-, 4- or 8-week pattern
    block_weeks?: number
    calibration_week?: boolean // week 1: log what you actually did
    category?: PlanCategory | null
    goal?: Goal
    cardio?: { type: string | null } // cardio days: which kind
  }
  completed: boolean
  notes: string | null // the user's own words; never sent to any AI model
  can_complete: boolean
  source: 'generated' | 'custom' // custom = the user built this day with the Workout Builder
  can_override: boolean // today or later and not done
  planned: { day_type: 'workout' | 'rest' | 'cardio'; focus: string | null } | null // what "Use my plan" brings back
  /** The day-type selector's current pick. 'open' = nothing chosen yet ("I'll build it myself" mode). */
  choice: 'plan' | 'build' | 'cardio' | 'open'
  /** Done days only: a calorie range computed in code (Compendium MET method), or null. */
  calories: { low: number; high: number; rough: boolean; parts: { what: 'strength' | 'cardio' }[] } | null
  /** Per exercise: whether it takes a weight, the live suggestion (null = none), and what was logged. */
  weights: Record<string, { weighted: boolean; suggested_lb: number | null; logged_reps: number | null; logged_lb: number | null }>
  created_at: string
  updated_at: string
}

export interface CalendarRange {
  start: string
  end: string
  today: string
  needs_quiz: boolean
  needs_clinical_review: boolean
  page?: string
  entries: CalendarEntry[]
  cardio: CardioLog[] // the user's own activity log, shown even when there's no plan
  calendar_mode: CalendarMode | null
  needs_review: boolean // review mode, plan not reviewed yet: nothing is laid out
  plan?: PlanWindow | null // the 6-month plan's dates
}

export const fetchCalendar = (token: string, start: string, end: string) =>
  request<CalendarRange>(`/api/calendar?start=${start}&end=${end}`, {}, token)

export interface CalendarUpdateResult {
  entry: CalendarEntry
  swapped_with: number | null
  workout_logs_added: number
  workout_logs_removed: number
  // A red-flag note is still saved; the API sends a supportive message to show beside it (no AI involved).
  safety: { flagged: boolean; message?: string; red_flags?: string[] }
}

export const updateCalendarDay = (
  token: string,
  id: number,
  change: {
    date?: string
    notes?: string | null
    completed?: boolean
    /** With completed: true, the reps and weights actually done (weight only for exercises that take one). */
    log?: { exercise_id: string; reps?: number | null; weight_lb?: number | null }[]
  },
) => request<CalendarUpdateResult>(`/api/calendar/${id}`, { method: 'PATCH', body: JSON.stringify(change) }, token)

/** Build a custom workout for one calendar day (Workout Builder agent, same injury filter) and save it there. */
export const overrideCalendarDay = (token: string, id: number, body: WorkoutRequest) =>
  request<AgentResponse<WorkoutSession> & { entry: CalendarEntry }>(
    `/api/calendar/${id}/custom`,
    { method: 'POST', body: JSON.stringify(body) },
    token,
  )

/** Undo a custom day: the planned (generated) workout comes back. No AI involved. */
export const revertCalendarDay = (token: string, id: number) =>
  request<{ entry: CalendarEntry }>(`/api/calendar/${id}/custom`, { method: 'DELETE' }, token)

/** The day-type selector, "Use my plan": the generated day (a built or cardio day gets its planned day back). */
export const applyDayPlan = (token: string, id: number) =>
  request<{ entry: CalendarEntry }>(`/api/calendar/${id}/use-plan`, { method: 'POST' }, token)

/** The day-type selector, "Add cardio": a cardio day, done once you log cardio on it. No AI. */
export const makeCardioDay = (token: string, id: number, cardioType: string | null) =>
  request<{ entry: CalendarEntry }>(
    `/api/calendar/${id}/cardio-day`,
    { method: 'POST', body: JSON.stringify({ cardio_type: cardioType }) },
    token,
  )

/** The progress marker at the top of the calendar: numbers and words both from code, no AI. */
export interface CalendarProgress {
  available: boolean
  reason?: string
  goal_status?: string
  headline?: string
  items?: { kind: 'sessions' | 'minutes' | 'energy' | 'weight_change' | 'fun_fact'; text: string; anchor?: string; rough?: boolean }[]
  heuristic_note?: string
  caveats_anchor?: string
}

export const fetchCalendarProgress = (token: string, weekStart: string) =>
  request<CalendarProgress>(`/api/calendar/progress?week_start=${weekStart}`, {}, token)

/** The Dashboard's streak card (GET /api/progress/streak). Code only, no AI. */
export interface StreakStats {
  found: boolean
  current_streak_days: number
  longest_streak_days: number
  active_days_last_30: number
  last_workout_date: string | null
  rest_day_suggested: boolean
  badges: { days: number; earned: boolean }[]
  next_badge: { days: number; to_go: number } | null
  definition: string
}

export const fetchStreak = (token: string) => request<StreakStats>('/api/progress/streak', {}, token)

// ---------------------------------------------------------------- Workout Reviewer

/** The 4 workout groups every plan is built from; the reviewer checks a session against these. */
export type WorkoutGroup = 'cardio' | 'upper' | 'lower' | 'mobility_core'
export const WORKOUT_GROUP_LABELS: Record<WorkoutGroup, string> = {
  cardio: 'Cardio',
  upper: 'Upper body',
  lower: 'Lower body',
  mobility_core: 'Mobility + core',
}

/** A review computed by code (coverage + a Compendium-based estimate range); `summary` is the AI's narration of
 *  it, or a plain code-written one (`summary_by: 'code'`) if the AI's draft used a number the code didn't give. */
export interface WorkoutReview {
  exercises: {
    name: string
    muscle_group: MuscleGroup
    force: 'push' | 'pull' | 'static' | null
    workout_groups: WorkoutGroup[]
  }[]
  coverage: {
    groups_hit: { group: WorkoutGroup; label: string; exercises: number }[]
    groups_missing: WorkoutGroup[]
    suggestion: string | null
    upper_body_balance: { push: number; pull: number; static: number; unclassified: number; note: string }
    notes: string[]
  }
  estimate:
    | { available: false; reason: string }
    | {
        available: true
        session_minutes: number
        per_session_kcal: { low: number; high: number }
        sessions_per_week: number | null
        weekly_kcal: { low: number; high: number } | null
        weight_change: {
          weeks: number
          pounds: { low: number; high: number }
          label: string
          cdc_context: string
        } | null
        method: { formula: string; low: { met: number; code: string; activity: string }; high: { met: number; code: string; activity: string } }
        caveats: string[]
      }
  citations: { id: string; name: string; url: string | null }[]
  summary: string
  summary_by: 'model' | 'code'
}

export const reviewWorkout = (
  token: string,
  items: { exercise_id: string; sets: number; reps: string; rest_seconds: number }[],
) =>
  request<AgentResponse<WorkoutReview>>('/api/workouts/review', { method: 'POST', body: JSON.stringify({ items }) }, token)

export const reviewCalendarDay = (token: string, id: number) =>
  request<AgentResponse<WorkoutReview>>(`/api/calendar/${id}/review`, { method: 'POST' }, token)

// ---------------------------------------------------------------- calendar mode, plan review, Save to calendar

export const setCalendarMode = (token: string, mode: CalendarMode) =>
  request<{ calendar_mode: CalendarMode; needs_review: boolean; laid_out: number }>(
    '/api/calendar/mode',
    { method: 'PUT', body: JSON.stringify({ mode }) },
    token,
  )

export interface PlanReview {
  plan: WeeklyProgram
  swaps: Record<string, string>
  calendar_mode: CalendarMode
  reviewed: boolean
}

export const fetchPlanReview = (token: string) => request<PlanReview>('/api/calendar/review', {}, token)

export const finalizePlanReview = (token: string, swaps: Record<string, string>) =>
  request<{ swaps: Record<string, string>; laid_out: number }>(
    '/api/calendar/review',
    { method: 'POST', body: JSON.stringify({ swaps }) },
    token,
  )

/** Put a session the Workout Builder built (by its id) onto a calendar day; extends the calendar if needed. */
export const saveBuiltToCalendar = (token: string, builtId: number, date: string) =>
  request<{ entry: CalendarEntry; days_added: number }>(
    '/api/calendar/save-built',
    { method: 'POST', body: JSON.stringify({ built_id: builtId, date }) },
    token,
  )

// ---------------------------------------------------------------- cardio log (no AI; your own record)

/** A calorie range computed in code (Compendium MET values x your weight), or why there isn't one. */
export type CardioEstimate =
  | { available: false; reason: string }
  | { available: true; kcal: { low: number; high: number }; basis: string; rough: boolean; caveats: string[] }

export type CardioMeasure = 'duration' | 'steps' | 'distance'

export interface CardioLog {
  id: number
  date: string
  activity: string | null
  exercise_id: string | null
  exercise_name: string | null
  cardio_type: string | null
  cardio_type_label: string | null
  measure: CardioMeasure
  duration_minutes: number | null
  steps: number | null
  distance_miles: number | null
  estimate: CardioEstimate
  created_at: string
}

export interface CardioExercise {
  id: string
  name: string
  equipment_needed: string[]
  difficulty: string
  cardio_type: string
}

export interface CardioType {
  value: string
  label: string
  distance: boolean // can be measured by distance
  steps: boolean // can be measured by steps
  estimate: boolean // has a calorie estimate ("Something else" doesn't)
}

export const fetchCardioExercises = () => getJson<CardioExercise[]>('/api/cardio/exercises')
export const fetchCardioTypes = () => getJson<CardioType[]>('/api/cardio/types')

export const logCardio = (
  token: string,
  body: {
    date: string
    activity?: string
    exercise_id?: string
    cardio_type?: string
    measure: CardioMeasure
    duration_minutes?: number
    steps?: number
    distance?: number
    distance_unit?: 'mi' | 'km'
  },
) =>
  request<{ log: CardioLog; safety: { flagged: boolean; message?: string }; calendar_entry_updated: number | null }>(
    '/api/cardio',
    { method: 'POST', body: JSON.stringify(body) },
    token,
  )

export const deleteCardio = (token: string, id: number) =>
  request<{ deleted: boolean }>(`/api/cardio/${id}`, { method: 'DELETE' }, token)

