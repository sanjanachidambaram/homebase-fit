-- HomeBase Fit database schema (SQLite).
--
-- Conventions:
--   * JSON columns hold JSON text and are checked with json_valid().
--   * Dates are ISO text: date = 'YYYY-MM-DD', timestamps = 'YYYY-MM-DDTHH:MM:SSZ' (UTC).
--   * Injury tags are lower_back | knee | shoulder everywhere (quiz answers,
--     exercises.injury_contraindications, program_templates.injury_focus).
--   * Content tables (quiz_questions, exercises, program_templates,
--     program_template_exercises, basics_articles) are loaded from content/
--     by app/db/seed.py. User tables start empty.

PRAGMA foreign_keys = ON;

-- ---------------------------------------------------------------- users

CREATE TABLE users (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    email         TEXT NOT NULL UNIQUE COLLATE NOCASE,
    password_hash TEXT NOT NULL,
    created_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- The questions shown in the onboarding quiz (from content/quiz/quiz_questions.yaml).
CREATE TABLE quiz_questions (
    id            TEXT PRIMARY KEY,                -- e.g. 'goals', 'injuries'
    order_index   INTEGER NOT NULL,
    prompt        TEXT NOT NULL,
    question_type TEXT NOT NULL CHECK (question_type IN ('multi_select', 'single_select', 'number', 'text')),
    options       TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(options)),   -- [{value, label}]
    settings      TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(settings)),  -- unit, min, max, exclusive, allow_free_text, ...
    required      INTEGER NOT NULL DEFAULT 1 CHECK (required IN (0, 1))
);

-- One row per user: the structured UserProfile the Onboarding Agent produces.
CREATE TABLE quiz_profiles (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    goals        TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(goals)),         -- ["weight_loss", "rehab"]
    timeline     TEXT,                                                         -- '4_weeks' | '8_weeks' | '12_weeks' | 'no_deadline'
    injury_flags TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(injury_flags)),  -- ["lower_back"]
    injury_notes TEXT,                                                         -- free text from the quiz
    age          INTEGER CHECK (age BETWEEN 13 AND 120),
    weight       REAL CHECK (weight > 0),                                      -- lb
    height       REAL CHECK (height > 0),                                      -- in
    created_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    updated_at   TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now'))
);

-- ---------------------------------------------------------------- content

CREATE TABLE exercises (
    id                       TEXT PRIMARY KEY,       -- slug, also the demo media file name
    name                     TEXT NOT NULL,
    muscle_group             TEXT NOT NULL CHECK (muscle_group IN ('legs', 'arms', 'back', 'core', 'full_body')),
    equipment_needed         TEXT NOT NULL DEFAULT '["none"]' CHECK (json_valid(equipment_needed)),        -- ["dumbbells"]
    difficulty               TEXT NOT NULL CHECK (difficulty IN ('beginner', 'intermediate', 'advanced')),
    injury_contraindications TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(injury_contraindications)),       -- ["knee"]
    demo_media_path          TEXT,                   -- relative to project root
    instructions             TEXT NOT NULL,
    est_time_seconds         INTEGER NOT NULL CHECK (est_time_seconds > 0)
);
CREATE INDEX idx_exercises_muscle_group ON exercises(muscle_group);

CREATE TABLE program_templates (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT NOT NULL UNIQUE,
    goal_tags         TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(goal_tags)),     -- ["weight_loss", "rehab"]
    injury_focus      TEXT NOT NULL DEFAULT '[]' CHECK (json_valid(injury_focus)),  -- ["lower_back"]
    description       TEXT NOT NULL,
    science_rationale TEXT NOT NULL,
    created_by        TEXT NOT NULL,
    source_file       TEXT                                                          -- content/programs/<file>.yaml
);

CREATE TABLE program_template_exercises (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    program_id  INTEGER NOT NULL REFERENCES program_templates(id) ON DELETE CASCADE,
    exercise_id TEXT NOT NULL REFERENCES exercises(id),
    day_of_week INTEGER NOT NULL CHECK (day_of_week BETWEEN 1 AND 7),  -- 1 = Monday ... 7 = Sunday
    sets        INTEGER NOT NULL CHECK (sets > 0),
    reps        TEXT NOT NULL,                                         -- "12", "30s", "8 each side"
    order_index INTEGER NOT NULL,
    UNIQUE (program_id, day_of_week, order_index)
);
CREATE INDEX idx_pte_program ON program_template_exercises(program_id, day_of_week, order_index);

CREATE TABLE basics_articles (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    slug        TEXT NOT NULL UNIQUE,   -- file name without .md
    title       TEXT NOT NULL,
    category    TEXT NOT NULL,
    content     TEXT NOT NULL,          -- markdown body
    media_path  TEXT
);

-- ---------------------------------------------------------------- user activity

CREATE TABLE workout_logs (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id          INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date             TEXT NOT NULL,                                   -- YYYY-MM-DD
    exercise_id      TEXT REFERENCES exercises(id),                   -- NULL for a whole-session entry
    program_id       INTEGER REFERENCES program_templates(id),        -- NULL for a custom session
    sets             INTEGER CHECK (sets >= 0),
    reps             INTEGER CHECK (reps >= 0),
    weight_used      REAL CHECK (weight_used >= 0),                   -- lb; NULL for bodyweight
    duration_seconds INTEGER CHECK (duration_seconds >= 0),
    notes            TEXT
);
CREATE INDEX idx_workout_logs_user_date ON workout_logs(user_id, date);

CREATE TABLE measurements (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    date         TEXT NOT NULL,                                                    -- YYYY-MM-DD
    body_weight  REAL CHECK (body_weight > 0),                                     -- lb
    measurements TEXT NOT NULL DEFAULT '{}' CHECK (json_valid(measurements))       -- {"waist_in": 30.5, "hips_in": 38}
);
CREATE INDEX idx_measurements_user_date ON measurements(user_id, date);

-- ---------------------------------------------------------------- safety

-- Every time the red-flag / injury-language redirect fires.
CREATE TABLE safety_events (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE SET NULL,   -- NULL if not signed in
    timestamp    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%SZ', 'now')),
    source       TEXT NOT NULL CHECK (source IN ('quiz', 'basics_qa')),
    trigger_text TEXT NOT NULL,     -- the user text that tripped the check
    action_taken TEXT NOT NULL      -- e.g. 'redirected_to_professional'
);
CREATE INDEX idx_safety_events_time ON safety_events(timestamp);
CREATE INDEX idx_safety_events_source ON safety_events(source, timestamp);

-- Display-ready view for the safety report: newest first, with the user's email.
CREATE VIEW safety_events_report AS
SELECT s.id,
       s.timestamp,
       s.source,
       COALESCE(u.email, '(anonymous)') AS user_email,
       s.trigger_text,
       s.action_taken
FROM safety_events s
LEFT JOIN users u ON u.id = s.user_id
ORDER BY s.timestamp DESC, s.id DESC;
