-- HomeBase Fit database schema (SQLite).
--
-- Conventions:
--   * JSON columns hold JSON text and are checked with json_valid().
--   * Dates are ISO text: date = 'YYYY-MM-DD', timestamps = 'YYYY-MM-DDTHH:MM:SSZ' (UTC).
--   * Injury tags are neck | shoulder | upper_back | lower_back | wrist | hip | knee | ankle everywhere (quiz answers,
--     exercises.injury_contraindications).
--   * Content tables (sources, quiz_questions, exercises, goal_protocols, basics_articles)
--     are loaded from content/ by app/db/seed.py. User tables start empty.
--   * There are no stored programs: each user's weekly plan is generated on request, in code,
--     from their quiz profile + goal_protocols + exercises (app/services/program_generator.py).

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- users

-- Deleting a user (DELETE /api/users/{id}) removes their quiz_profiles,
-- exercise_favorites, workout_logs, measurements, and safety_events too (ON DELETE CASCADE, plus
-- explicit deletes in app/users.py). AUTOINCREMENT means ids are never reused.
-- username and first_name identify the person, so neither ever reaches an agent (app/agents/context.py,
-- EXCLUDED_USER_FIELDS). Accounts from before usernames (2026-10-23) kept their old email as their username, so
-- they still sign in with what they typed before (app/db/reset.py, RENAMED_COLUMNS); their first_name is NULL.
CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    username      TEXT NOT NULL UNIQUE COLLATE NOCASE,
    first_name    TEXT,                            -- only for the Dashboard greeting ("Hi Sarah")
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- The questions shown in the onboarding quiz (from content/quiz/quiz_questions.yaml).
CREATE TABLE quiz_questions (
    id            TEXT PRIMARY KEY,                -- e.g. 'goals', 'injuries'
    order_index   INTEGER NOT NULL,
    prompt        TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('multi_select', 'single_select', 'number', 'text', 'date')),
    options       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(options)),   -- [{value, label, description?}]
    settings      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(settings)),  -- unit, min, max, help_text, health, ...
    required      INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0, 1))
);

-- One row per user: their quiz answers (structured intake; no LLM involved).
-- No free text is asked any more (the "Anything else we should know?" box was removed 2026-10-25). pregnancy_status
-- and weight are never sent to the AI model (the PII boundary in app/agents/context.py exposes only the goal and
-- the injury flags).
CREATE TABLE quiz_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    -- One goal (2026-10-25 rewrite). It picks the week structure, the protocol and how weights go up.
    goal         TEXT NOT NULL CHECK (goal IN ('stronger', 'lose_weight', 'feel_good')),
    injury_flags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(injury_flags)),  -- ["lower_back"]
    experience_level       TEXT CHECK (experience_level IN ('beginner', 'intermediate', 'advanced')),
    equipment              TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(equipment)),  -- ["dumbbells", "mat"]
    pregnancy_status       TEXT CHECK (pregnancy_status IN ('none', 'pregnant', 'postpartum')),
    -- Pregnant / postpartum answers are flagged for clinical (OB-GYN) review. Computed by the database,
    -- so it can never disagree with pregnancy_status. No plan is generated while this is 1.
    needs_clinical_review  INTEGER GENERATED ALWAYS AS (pregnancy_status IN ('pregnant', 'postpartum')) STORED,
    -- Asked only when the goal is losing weight, and only stored then (the CHECK below): lb.
    weight                 REAL CHECK (weight > 0),
    goal_weight            REAL CHECK (goal_weight > 0),
    -- Medical disclaimer acknowledgment. The quiz can't be saved without it,
    -- and the table-level CHECK below means the database refuses it too.
    consent_accepted    INTEGER NOT NULL CHECK (consent_accepted IN (0, 1)),
    consent_accepted_at TEXT,                                                  -- UTC timestamp of acceptance
    consent_version     TEXT,                                                  -- which disclaimer text was accepted
    -- How the calendar gets filled (asked after the quiz, changeable in Settings):
    --   generated  the quiz-generated plan, laid out on the calendar (the default)
    --   review     the generated plan, but the user reviews and swaps exercises before any day is laid out
    --   self       no generated workouts: days are open, and the user builds them (Build Your Own)
    calendar_mode   TEXT NOT NULL DEFAULT 'generated' CHECK (calendar_mode IN ('generated', 'review', 'self')),
    plan_reviewed   INTEGER NOT NULL DEFAULT 0 CHECK (plan_reviewed IN (0, 1)),   -- review mode: finalized yet?
    -- Review-mode swaps, {"original exercise id": "replacement id"}. Only replacements from the same injury- and
    -- equipment-filtered pool are accepted (checked when saved AND when applied). Cleared on every quiz save.
    plan_swaps      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(plan_swaps) AND json_type(plan_swaps) = 'object'),
    -- Week 1 of the current plan (YYYY-MM-DD): which week of the 2/4/8-week pattern a date falls in, and how far
    -- weights have gone up, count from here. Reset on every quiz save.
    plan_started_on TEXT,
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (consent_accepted = 1 AND consent_accepted_at IS NOT NULL AND consent_version IS NOT NULL),
    CHECK (goal = 'lose_weight' OR (weight IS NULL AND goal_weight IS NULL))   -- weight only for the weight-loss path
);

-- ---------------------------------------------------------------- content

-- Source registry (from content/sources.yaml). Served at GET /api/sources.
CREATE TABLE sources (
    id          TEXT PRIMARY KEY,           -- e.g. 'free-exercise-db'
    order_index INTEGER NOT NULL,
    name        TEXT NOT NULL,
    url         TEXT,
    license     TEXT NOT NULL,
    used_for    TEXT NOT NULL,
    status      TEXT NOT NULL CHECK (status IN ('active', 'placeholder', 'pending'))
);

CREATE TABLE exercises (
    id                       TEXT PRIMARY KEY,       -- hand-authored: slug; imported: the dataset's own id
    name                     TEXT NOT NULL,
    muscle_group             TEXT NOT NULL CHECK (muscle_group IN ('legs', 'arms', 'chest', 'shoulders', 'back', 'core', 'full_body')),
    equipment_needed         TEXT NOT NULL DEFAULT '["none"]' CHECK (json_valid(equipment_needed)),        -- ["dumbbells"]
    difficulty               TEXT NOT NULL CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    -- Movement direction (free-exercise-db's "force"; hand-authored ones set it in exercises.yaml). NULL = no single
    -- direction. Push plan days never get 'pull' moves and Pull days never get 'push' moves (program_generator.py).
    force                    TEXT CHECK (force IS NULL OR force IN ('push', 'pull', 'static')),
    injury_contraindications TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(injury_contraindications)),       -- ["knee"]
    -- How far to trust injury_contraindications. An empty list on an 'untagged'
    -- exercise means "nobody has checked", NOT "safe for every injury".
    --   untagged     no injury review at all (every imported exercise starts here)
    --   draft        tags drafted but not yet reviewed by a PT
    --   pt_reviewed  tags confirmed by a PT
    contraindication_status  TEXT NOT NULL CHECK (contraindication_status IN ('untagged', 'draft', 'pt_reviewed')),
    -- Why each tag in injury_contraindications is there, one entry per tag (the seed checks they match):
    --   {"knee": {"reasoning": "...", "tier": "ai_drafted" | "pt_reviewed", "source": "..."}}
    -- reasoning is plain-language exercise science, never a citation. tier ai_drafted = written by AI, not yet
    -- reviewed, with source "Pending review by a licensed physical therapist"; pt_reviewed = source names the PT.
    injury_rationale         TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(injury_rationale) AND json_type(injury_rationale) = 'object'),
    demo_media_path          TEXT,                   -- relative to project root; the file may not exist yet
    -- How the frontend should render demo_media_path: <img> for 'image' and 'gif',
    -- <video> for 'video'. Set by the seed from the file extension; NULL when
    -- there is no media path. A video can replace an image with no schema change.
    media_type               TEXT CHECK (media_type IN ('image', 'gif', 'video')),
    instructions             TEXT NOT NULL,
    est_time_seconds         INTEGER NOT NULL CHECK (est_time_seconds > 0),
    category                 TEXT,                   -- dataset category: strength, stretching, cardio, ... (NULL for hand-authored)
    primary_muscles          TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(primary_muscles)),     -- dataset's own muscle names
    secondary_muscles        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(secondary_muscles)),
    source_dataset           TEXT NOT NULL REFERENCES sources(id),  -- 'placeholder-authored' | 'free-exercise-db' | ...
    -- Same review fields as programs and articles: 'placeholder' content is
    -- flagged "Content pending expert review" by the API. Every exercise starts
    -- as placeholder, including the imported ones, until a PT reviews it.
    citations                TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(citations) AND json_type(citations) = 'array'),
    status                   TEXT NOT NULL DEFAULT 'placeholder' CHECK (status IN ('placeholder', 'pt_reviewed'))
);
CREATE INDEX idx_exercises_muscle_group ON exercises(muscle_group);
CREATE INDEX idx_exercises_source ON exercises(source_dataset);

-- The training parameters behind every generated plan: one row per goal x experience level
-- (from content/protocols/goal_protocols.yaml). Small on purpose, so a PT can review all of it.
-- The generator reads sets/reps/rest from here and never invents them per exercise.
CREATE TABLE goal_protocols (
    id                     INTEGER PRIMARY KEY AUTOINCREMENT,
    goal                   TEXT NOT NULL CHECK (goal IN ('stronger', 'lose_weight', 'feel_good')),
    experience_level       TEXT NOT NULL CHECK (experience_level IN ('beginner', 'intermediate', 'advanced')),
    session_length_minutes INTEGER NOT NULL CHECK (session_length_minutes BETWEEN 15 AND 60),
    sets_range             TEXT NOT NULL,      -- "2-3" or "3"
    reps_range             TEXT NOT NULL,      -- "12-15" or "10" (Getting stronger: a rough guide; reps are the user's call)
    rest_seconds           INTEGER NOT NULL CHECK (rest_seconds BETWEEN 0 AND 300),
    progression_note       TEXT NOT NULL,
    reference_notes        TEXT,
    source_id              TEXT NOT NULL REFERENCES sources(id),
    -- Citation integrity: [{"claim": ..., "source": ...}]; 'placeholder' rows are flagged
    -- "Content pending expert review" everywhere they're shown.
    citations              TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(citations) AND json_type(citations) = 'array'),
    status                 TEXT NOT NULL DEFAULT 'placeholder' CHECK (status IN ('placeholder', 'pt_reviewed')),
    UNIQUE (goal, experience_level)
);

CREATE TABLE basics_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,   -- file name without .md
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    content     TEXT NOT NULL,          -- markdown body
    media_path  TEXT,
    source_id   TEXT NOT NULL REFERENCES sources(id),
    citations   TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(citations) AND json_type(citations) = 'array'),
    status      TEXT NOT NULL DEFAULT 'placeholder' CHECK (status IN ('placeholder', 'pt_reviewed'))
);

-- ---------------------------------------------------------------- bookkeeping

-- Which homebase_original.db the working copy was last built or refreshed from (key 'original_sha256'). On a
-- persistent disk the working copy outlives deploys; when a deploy ships a new original (new content or schema),
-- startup sees the mismatch and refreshes the working copy, keeping every account (app/db/__init__.py).
CREATE TABLE app_meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- ---------------------------------------------------------------- user activity

-- Workout Builder sessions as the server built them, so "Save to calendar" can only ever save a session that went
-- through the builder's checks (a client can't send its own exercise list). Pruned to the last week; deleted with
-- the user.
CREATE TABLE built_workouts (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    request     TEXT NOT NULL CHECK (json_valid(request)),
    session     TEXT NOT NULL CHECK (json_valid(session)),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- Cardio the user did (a log, not a recommendation; no AI). Free text ("ran 20 min") or one of the library's cardio
-- exercises, measured however they like: minutes, steps, or distance (measure says which; distance is stored in
-- miles). cardio_type (walking, running, ...) picks the Compendium MET codes for the calorie estimate
-- (app/services/cardio_estimate.py); NULL = no estimate. activity is the user's own words, like calendar notes:
-- never sent to any model, red-flag checked when saved (safety_events source 'cardio_log'). Each log also writes one
-- workout_logs row, so the Coach's streak and rest-day checks see the activity.
CREATE TABLE cardio_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date             TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),
    activity         TEXT CHECK (activity IS NULL OR length(activity) <= 80),
    exercise_id      TEXT REFERENCES exercises(id),
    cardio_type      TEXT,
    measure          TEXT NOT NULL DEFAULT 'duration' CHECK (measure IN ('duration', 'steps', 'distance')),
    duration_minutes INTEGER CHECK (duration_minutes BETWEEN 1 AND 600),
    steps            INTEGER CHECK (steps BETWEEN 1 AND 100000),
    distance_miles   REAL CHECK (distance_miles > 0 AND distance_miles <= 200),
    created_at       TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    CHECK (activity IS NOT NULL OR exercise_id IS NOT NULL),
    CHECK ((measure = 'duration') = (duration_minutes IS NOT NULL)),
    CHECK ((measure = 'steps') = (steps IS NOT NULL)),
    CHECK ((measure = 'distance') = (distance_miles IS NOT NULL))
);
CREATE INDEX idx_cardio_logs_user_date ON cardio_logs(user_id, date);

-- The generated plan laid out on real dates (app/calendar.py): 4 weeks from the day the quiz is saved.
-- workout_content is a SNAPSHOT of that day's plan when the entry was made, so a later change to the
-- generator never silently rewrites a scheduled day. A retake only replaces entries dated today or later
-- that are not completed and have no notes; past days and anything the user logged or wrote on are kept.
-- notes are the user's own words: never sent to any AI model (shared_rules.md rule 2), and checked for
-- red flags in code when saved (safety_events source 'calendar_note').
-- A day can be overridden with a custom workout from the Workout Builder: source = 'custom', and the generated
-- day it replaced is kept in planned_content ({"day_type", "workout_content"}) so it can be restored. A retake
-- never replaces a custom day either. A cardio day (day_type 'cardio', chosen with "Add cardio") is a custom day
-- too; it counts as done once cardio is logged on its date (cardio_logs), not with the strength-day toggle.
CREATE TABLE calendar_entries (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date            TEXT NOT NULL CHECK (date GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]'),   -- YYYY-MM-DD
    day_type        TEXT NOT NULL CHECK (day_type IN ('workout', 'rest', 'cardio')),
    workout_content TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(workout_content) AND json_type(workout_content) = 'object'),
    completed       INTEGER NOT NULL DEFAULT 0 CHECK (completed IN (0, 1)),
    notes           TEXT,
    source          TEXT NOT NULL DEFAULT 'generated' CHECK (source IN ('generated', 'custom')),
    planned_content TEXT CHECK (planned_content IS NULL OR json_valid(planned_content)),   -- the generated day, kept
    created_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at      TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (user_id, date),         -- one day widget per date; moving onto a taken date swaps the two
    CHECK ((source = 'custom') = (planned_content IS NOT NULL))   -- a custom day can always be reverted
);

CREATE TABLE workout_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date             TEXT NOT NULL,                                   -- YYYY-MM-DD
    exercise_id      TEXT REFERENCES exercises(id),                   -- NULL for a whole-session entry
    plan_day         TEXT CHECK (plan_day IN ('mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun')),  -- set when logged from the weekly plan
    sets             INTEGER CHECK (sets >= 0),
    reps             INTEGER CHECK (reps >= 0),
    weight_used      REAL CHECK (weight_used >= 0),                   -- lb; NULL for bodyweight
    duration_seconds INTEGER CHECK (duration_seconds >= 0),
    notes            TEXT,
    -- Set when the row was written by marking a calendar day completed (and removed if it's un-marked).
    -- Calendar notes are NOT copied into notes above.
    calendar_entry_id INTEGER REFERENCES calendar_entries(id) ON DELETE CASCADE,
    -- Set when the row was written by a cardio log (removed with it). The activity text is NOT copied.
    cardio_log_id     INTEGER REFERENCES cardio_logs(id) ON DELETE CASCADE
);
CREATE INDEX idx_workout_logs_user_date ON workout_logs(user_id, date);
CREATE INDEX idx_workout_logs_calendar ON workout_logs(calendar_entry_id);

-- A user's favorited ("faved") exercises. Deleted with the user.
CREATE TABLE exercise_favorites (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL REFERENCES exercises(id),
    created_at  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    UNIQUE (user_id, exercise_id)
);

CREATE TABLE measurements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,                                                    -- YYYY-MM-DD
    body_weight  REAL CHECK (body_weight > 0),                                     -- lb
    measurements TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(measurements))       -- {"waist_in": 30.5, "hips_in": 38}
);
CREATE INDEX idx_measurements_user_date ON measurements(user_id, date);

-- ---------------------------------------------------------------- safety

-- Every time the red-flag / injury-language check fires (Workout Basics questions, calendar notes).
-- Deleting a user deletes their events too (trigger_text is their own words).
CREATE TABLE safety_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,    -- NULL if not signed in
    timestamp    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source       TEXT NOT NULL CHECK (source IN ('quiz', 'basics_qa', 'calendar_note', 'cardio_log')),
    trigger_text TEXT NOT NULL,     -- the user text that tripped the check
    action_taken TEXT NOT NULL      -- e.g. 'redirected_to_professional'
);
CREATE INDEX idx_safety_events_time ON safety_events(timestamp);
CREATE INDEX idx_safety_events_source ON safety_events(source, timestamp);

-- ---------------------------------------------------------------- agent token log

-- One row per agent call (every call, including failed ones), with token counts measured
-- by PydanticAI's usage tracking. This is the source for the tokenomics report.
-- Deleting a user keeps their rows for the token statistics but clears user_id.
-- app/db/reset.py carries these rows over when it resets the working database.
CREATE TABLE agent_runs (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_name    TEXT NOT NULL,      -- program_architect | workout_builder | coach | basics
    user_id       INTEGER REFERENCES users(id) ON DELETE SET NULL,
    input_tokens  INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cached_tokens INTEGER NOT NULL DEFAULT 0,   -- input tokens served from the provider's prompt cache
    requests      INTEGER NOT NULL DEFAULT 0,   -- model round trips in this call
    tool_calls    INTEGER NOT NULL DEFAULT 0,
    model         TEXT NOT NULL,
    route         TEXT NOT NULL,      -- e.g. 'POST /api/basics/ask'
    status        TEXT NOT NULL CHECK (status IN ('ok', 'error')),
    error_type    TEXT,               -- exception class name when status = 'error'
    duration_ms   INTEGER,
    timestamp     TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    -- Gateway response cache. The Portkey gateway replays a stored answer for an identical request; a
    -- replay costs no provider tokens. Detected per model request from the response's created_at
    -- (older than when the gateway received the request = replay); see app/agents/harness.py.
    --   hit: every model request in this call was a replay   miss: none were   partial: some were
    --   unknown: couldn't tell (no model HTTP traffic seen, e.g. tests; or rows logged before this column)
    gateway_cache_status TEXT NOT NULL DEFAULT 'unknown'
        CHECK (gateway_cache_status IN ('hit', 'miss', 'partial', 'unknown')),
    gateway_cache_hits   INTEGER NOT NULL DEFAULT 0,   -- how many of `requests` were replays
    -- Tokens the provider actually processed for this call (replayed requests excluded).
    -- input_tokens/output_tokens above include replays. NULL when gateway_cache_status is 'unknown'.
    fresh_input_tokens   INTEGER,
    fresh_output_tokens  INTEGER
);
CREATE INDEX idx_agent_runs_agent_time ON agent_runs(agent_name, timestamp);

-- Display-ready view for the safety report: newest first, with the user's username.
CREATE VIEW safety_events_report AS
SELECT s.id,
       s.timestamp,
       s.source,
       COALESCE(u.username, '(anonymous)') AS username,
       s.trigger_text,
       s.action_taken
FROM safety_events s
LEFT JOIN users u ON u.id = s.user_id
ORDER BY s.timestamp DESC, s.id DESC;
