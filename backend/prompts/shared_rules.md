# HARD RULES FOR ALL HOMEBASE FIT AGENTS

These are the rules every agent follows. Each agent's prompt file restates the ones that apply to it,
but **a prompt instruction alone never counts**: every rule below is also enforced by code, and the
"Enforced in code" lines say exactly where. Tests: `backend/tests/test_agents.py`, `test_mcp_tools.py`.

## The agent team (decided 2026-10-22)

Exactly four LLM agents, each started by one user action. They never call each other.

| Agent | Route | Model-visible tools | Code |
|---|---|---|---|
| Program Architect | `POST /api/programs/recommend` | none: it explains a plan the code already built | `app/agents/program_architect.py` |
| Workout Builder | `POST /api/workouts/build` | get_user_profile, search_exercises | `app/agents/workout_builder.py` |
| Coach | `GET /api/coach/summary` | get_progress_summary, check_goal_achievement, compute_strength_equivalents | `app/agents/coach.py` |
| Fitness Basics | `POST /api/basics/ask` | search_basics_kb | `app/agents/basics.py` |

Deliberately NOT LLM agents: onboarding (the quiz is structured intake, `app/users.py`), the safety
check (a code-level red-flag filter, `app/agents/safety.py`, rule 3), and **plan building** (a deterministic
generator, `app/services/program_generator.py`, rule 6). Cheaper, more reliable, testable.

All data access goes through the MCP tool server (`app/mcp_server/server.py`) via `McpGateway` in
`app/agents/harness.py`. Every agent call is logged with measured tokens in `agent_runs`.

## 1. Citation integrity (Program Architect and Fitness Basics)

- Never state anything as scientific fact ("research shows", "science says", "proven", "studies",
  "evidence-based", "backed by science") unless the goal protocol or article it comes from has a citation
  in its `citations` list in the database.
- If the verified content doesn't cover the question, the answer is:
  **"I don't have verified information on that. Please consult a doctor or physical therapist."**
  Never guess or fill gaps from general knowledge.
- Content with `status: placeholder` may be passed on as "our guide says" / "your plan", but always
  with its "pending expert review" flag, and never as established or scientific fact.
- Every answer names the articles (or the plan's protocol) it comes from, and their status and citations are shown.
- Numbers from `check_goal_achievement` come from simple app thresholds, not science. Never present them
  as science-backed.

**Enforced in code:**
1. Basics sources must be articles the tool returned in this run (output validator in `basics.py`). Status,
   review notice and citations are copied by code; the model can't write or upgrade them. The Program
   Architect gets the plan's protocol status and citations in its prompt and has no tools at all.
2. A science-claim check (`harness.makes_science_claim`) runs on every rationale and answer whose sources
   have no citations. The Basics agent is asked to rewrite, then falls back to the "no verified
   information" reply. The Program Architect's explanation is replaced with a plain one.
3. The Fitness Basics agent's ONLY tool is `search_basics_kb`. When the knowledge base has nothing for the
   question (`answerable: false`), the code replies "I don't have verified information..." itself
   **without calling the model**. Same for the Program Architect when no plan can be generated (pregnant or
   postpartum, rule 6): the code explains why without calling the model.

## 2. Privacy and user identity (all agents)

- User context comes only from `app/agents/context.py` (`agent_profile_for`): goals, timeline,
  injury_flags, age, weight, height. Never email, name, user id, password data, or free-text notes.
- The user is always the one in the sign-in token. Nothing the user types and nothing the model outputs
  can choose which user's data is read.
- **Calendar notes never reach any model, for any purpose.** They are the user's own words, on the same
  footing as `injury_notes` and `other_activity_notes`: stored in `calendar_entries.notes`, shown only to that
  user, and never read by `agent_profile_for`, any MCP tool, or any agent (not the Coach, not anything else).
  Marking a calendar day done writes `workout_logs` rows, and the note is **not** copied into them.
  Test: `test_calendar_notes_never_reach_any_model` runs every agent with a fake model that records everything
  it is sent (prompts, instructions, tool results) and checks a unique note never appears, then checks the
  progress tools' output directly.

**Enforced in code:**
1. The FastAPI routes (`app/agent_routes.py`) take the user only from the token; request bodies forbid
   extra fields, so `{"user_id": ...}` is rejected with 422, and query strings are ignored.
2. The tools the model sees have **no `user_id` parameter** (nor `injury_flags`, `checked_only`, or
   `equipment`). The agent code adds the session's user id before calling the MCP server. If the model
   tries to pass one, PydanticAI rejects the call as invalid arguments.
3. `test_user_cannot_reach_another_users_data` and `test_model_never_sees_user_id_injury_flags_or_checked_only`
   prove both: a manipulated model asking for another user's id only ever reaches the signed-in user's data.

## 3. Safety redirect (red flags, before any model call)

- A question with pain/injury warning signs (e.g. "sharp pain", "numbness", "can't move", "severe",
  "chest pain", "dizzy", "I think I tore my...", "my knee hurts") gets a fixed message pointing to a
  doctor or physical therapist. No exercise advice.

**Enforced in code:** `app/agents/safety.py` runs a regex check **before** the Basics agent. On a match the
agent is never called (no tokens are spent), a `safety_events` row is written (`source = 'basics_qa'`,
`action_taken = 'redirected_to_professional'`), and the fixed message is returned.
Test: `test_red_flag_question_never_reaches_the_agent` (spies on the agent and checks the row).
The term list is a placeholder for the PT/OB-GYN to review.

**Calendar notes** go through the same check (`app/calendar.py`) whenever a note is saved or changed, with one
difference: the note is **still saved** (it's the user's own log, and we never stop them writing in it). On a
match the API returns a supportive message pointing to a doctor or physical therapist, shown beside the note,
and writes a `safety_events` row (`source = 'calendar_note'`, `action_taken = 'note_saved_pointed_to_professional'`).
There is no AI call either way. Test: `test_red_flag_note_is_saved_logged_and_answered_without_ai`.

## 4. Injury filtering (the plan generator and the Workout Builder)

- Exercises tagged unsafe for the user's `injury_flags` (lower_back, knee, shoulder, wrist, ankle) are removed
  by the SQL in `app/mcp_server/search.py: search_exercises`, which both the MCP tool and the plan generator use.
- Most exercises have no injury tags yet (`untagged`). Untagged exercises always carry
  `injury_check: "not_yet_checked"` and must never be described as safe.
- **DECIDED (2026-10-22, project owner): users with an injury flag only ever get exercises that have
  injury tags.** For them `checked_only=true` is always passed to `search_exercises`, by the plan generator and
  by the Workout Builder alike. One function decides it: `app/safety_rules.py: checked_only_for`.
  Users with no injury flags can see untagged exercises, still flagged `not_yet_checked`.
- The injury tags are drafts (`injury_check: "drafted_not_pt_reviewed"`). That isn't confirmation of safety.

**Enforced in code:** `harness.harness_flags` sets `injury_flags` and `checked_only` from the profile, and the
tool wrappers add them to every MCP call. The model can't see or change them.
Tests: `test_injured_user_always_gets_checked_only`, `test_injury_filter_is_applied_during_generation`,
`test_every_injury_flag_forces_checked_only`.

## 5. Coach tone (design.md, section 7)

- Warm, upbeat, a little cheeky. Never body-shaming, guilt-tripping, or about food, eating, diets, or body
  weight. Celebrate showing up and consistency.
- `goal_status` and `overtraining_flag` (10+ days in a row) come from the tools, never from the model.
- Strength fun facts (`compute_strength_equivalents`) compare pounds lifted with **animals and objects only**
  (chihuahuas, raccoons, pandas, vending machines, elephants...): never food or drink, never the user's body or
  weight. Silly ballpark weights are fine; they're labelled as fun approximations, not measurements. Code picks
  the headline at random within the size tier the total reaches, so repeat visits vary. Test:
  `test_comparisons_are_about_objects_and_animals_never_food_or_bodies`.

**Enforced in code:** `coach.py` tone guard (a blocklist) sends a failing message back for a rewrite and
replaces it with a plain encouraging line if it still fails. The flags and the strength fun fact are
built by code from the tool results.

## 6. Building the weekly plan (code, not the model)

Every plan comes from `app/services/program_generator.py`: plain Python, no LLM call. Same profile in, same
plan out. The training parameters come only from `goal_protocols` (content/protocols/goal_protocols.yaml,
one row per goal x experience level, PT-reviewable); the generator never invents sets, reps, or rest.

- **Safety first.** Pregnant or postpartum (`needs_clinical_review`): no plan is generated until
  OB-GYN-reviewed guidance exists; the user is pointed to their OB-GYN or midwife. They also never reach
  ANY AI agent: the Workout Builder and Coach routes return 403, the Program Architect and Basics answer
  from code (the Basics red-flag check still runs and still logs), and the frontend sends them to
  `/pregnancy-support`. One check, `app/safety_rules.py: profile_needs_clinical_review`, decides it. Any injury flag:
  `checked_only=true` on every exercise search, no exceptions (rule 4).
- **Blending several goals** (e.g. weight loss + rehab). Where the goals' protocols differ, the more
  conservative value wins:
  - sessions per week: the fewest
  - session length: the shortest (and never longer than the user asked for)
  - split: the gentlest, in this order: full body > circuit > upper/lower > push/pull/legs
  - sets: the lower range
  - reps: the lighter-load (higher-rep) range
  - rest: the longest
  - status: placeholder if any goal's protocol is a placeholder; citations: all of them
- **Training days** = min(days the user has, the protocol's sessions per week), never more than 6 (a full
  rest day every week), and fewer if training + other regular activity would exceed 6 active days. At least 1.
- **Exercises**: per day, muscle groups from the split; picked from `search_exercises` with the user's
  equipment, injury flags and `checked_only`; matched to experience level; no Olympic lifts, strongman,
  powerlifting, or stretches in the main sets; no jumping/landing moves for rehab, any injury, or beginners.
  Muscle groups with nothing safe to offer are left out and the plan says so.
- **The Program Architect** only explains the finished plan, from the plan, the goals, and the protocol's
  status and citations. It has no tools and never sees age, weight, pregnancy status, notes, or the user id.

**Enforced in code and tested:** `tests/test_program_generator.py` (blending, days, the injury filter during
generation, equipment, pregnancy), `tests/test_plan_agent.py` (the agent's inputs, claims, and logging).

## 7. Numbers come from code (the Workout Reviewer, and any agent that narrates a calculation)

- The Workout Reviewer reviews a session someone built (Build Your Own, or a custom calendar day). Code computes
  everything: muscle-group coverage, push/pull balance (exercises.force), and the outcome estimate
  (`app/services/workout_review.py`). The agent only puts that result into words.
- **The model never produces a number.** Every number in its reply must appear in the data code gave it,
  written the same way. It may not compute, round, convert, add, or turn a range into a single figure.
- Estimates are always ranges, rounded outward, never a single number. Calories come from MET values in the
  2024 Adult Compendium of Physical Activities (1 MET = about 1 kcal per kg per hour; MET 3.5, code 02054, to
  MET 7.5, code 02020). Pounds appear only for people with a weight-loss goal, use the 3,500-calories-per-pound
  rule of thumb, and are always labelled "a rough, long-used approximation, not a precise prediction", with the
  caveat that exercise alone is usually a small piece of weight change compared with eating. Sources: the
  Compendium and the CDC pace guidance, both in `/api/sources`.
- Same privacy as every agent (rule 2): the model gets the computed review only, never the user's id, email,
  weight, or any free text. Pregnant / postpartum users get a 403 before anything is computed or sent.

**Enforced in code:** `app/agents/workout_reviewer.py` extracts every number in the reply and compares it with the
numbers in the model's input. Any number that isn't there sends the draft back; after two tries, and once more as
a final check before returning, the reply is replaced by a plain summary written by code. A tone guard like the
Coach's applies (no shaming, guilt or food talk; it allows "calories" and "pounds", which the estimate needs), plus
no promises ("you will lose..."). Tests: `tests/test_workout_review.py`.

## 8. Progressive overload (decided 2026-10-23)

- Plans do a little more over time, a general training principle: every 2 weeks, +1 rep up to the top of the
  protocol's rep range, then +1 set (reps back to the bottom) up to the top of its set range, then it holds. It never
  goes past the protocol's own ranges (which are what a PT will review), and the session still fits its time (the
  generator already plans for the top of the set range).
- It changes **only sets and reps**. Never which exercises are picked (the injury filter alone decides that, untouched)
  and never rest.
- Weeks count from `quiz_profiles.plan_started_on` (set whenever the quiz is saved; a retake is a new plan and starts
  week 1 again), so days laid out later, on a top-up or by "Save to calendar", get the right week.
- **DECISION: no automatic progression for anyone with an injury flag or a rehab goal.** Their sets and reps stay at
  the protocol's starting values, and the plan says why ("paused until a physical therapist has reviewed your plan").
  Reason: the protocols and the injury tags are unreviewed drafts, and raising training volume for someone working
  around an injury is a clinical judgment the app can't make. Flat is the most conservative option; it can be
  revisited once a PT has reviewed the rehab protocols. Pregnant / postpartum users have no plan at all (rule 6).

**Enforced in code:** `progression_enabled`, `progressed` and `exercise_for_week` in
`app/services/program_generator.py`; each calendar day's snapshot carries its `week` and `progression_step`.
Tests: `test_injured_and_rehab_profiles_do_not_progress_but_the_same_goal_without_injury_does`,
`test_an_injured_calendar_stays_flat_week_after_week`, `test_progression_never_goes_past_the_protocols_own_ranges`.

## 9. Cardio logs (decided 2026-10-23)

- A cardio log is something the user did, not something we recommend: free text ("ran 20 min") or one of the
  library's cardio exercises (free-exercise-db category "cardio"), plus minutes. **No AI, anywhere.**
- The free text is the user's own words, under the same rules as calendar notes (rule 2): never sent to any model,
  and checked by the code-only red-flag filter (rule 3) when saved. A match still saves the log, returns a supportive
  message, and writes a `safety_events` row (`source = 'cardio_log'`).
- Each log writes one `workout_logs` row (minutes, and the exercise if picked; never the text), so the Coach's streak
  and rest-day suggestion see the activity.
- **DECISION: pregnant / postpartum users can log cardio, in their own words only.** Reason: a log is a personal
  record, like a note: no AI, no exercise prescription, nothing generated for them. Keeping a record of the activity
  their own clinician okays is reasonable, and the red-flag check still runs, with a message that points to their
  OB-GYN or midwife (and to urgent care for severe or sudden symptoms). What they don't get is the library picker: a
  list of exercises shown to someone with no plan reads like a suggestion, which is exactly what we've held back until
  an OB-GYN has reviewed pregnancy guidance (rule 6). The API refuses `exercise_id` for them (403).

**Enforced in code:** `app/cardio.py`. Tests: `tests/test_cardio.py`
(`test_pregnant_users_can_log_in_their_own_words_only`, `test_cardio_text_never_reaches_any_model`,
`test_red_flag_in_a_cardio_log_is_saved_logged_and_answered_without_ai`).

## 10. Calendar population modes, and saving Build Your Own to the calendar

- After the quiz (and any time in Settings) the user picks how the calendar is filled: **generated** (the default),
  **review** (the generated plan, laid out only after they review it and optionally swap exercises), or **self** (open
  days they fill with Build Your Own). Every mode keeps per-day overrides, and the retake rules (rule 2 of the calendar:
  completed, noted and custom days are never replaced).
- Review swaps can only pick from the same injury-, equipment- and level-filtered pool the generator used for that slot
  (and the same Push/Pull direction). They're checked when saved (422 otherwise) and again every time the plan is built.
- "Save to calendar" from the Build Your Own page reuses the custom-day mechanism (source 'custom', kept on retake,
  revertible). The client sends only the id of a session the server's Workout Builder made and stored
  (`built_workouts`), never an exercise list, so nothing can skip the builder's injury filter. A date beyond the laid-out
  days extends the calendar up to it (up to 6 months ahead). Blocked for pregnant / postpartum users (403), like every
  plan feature.

