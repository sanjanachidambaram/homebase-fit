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

- User context comes only from `app/agents/context.py` (`agent_profile_for`): the goal and injury_flags (since
  2026-10-25; age, height and timeline are no longer asked, and weight never reaches a model). Never email, name,
  user id, password data, weight, or free-text notes.
- **Username and first name are identifying, exactly like email (decided 2026-10-23).** Sign-in uses a username,
  and sign-up asks for a first name, used only for the Dashboard greeting ("Hi Sarah"). Both live only in the
  `users` table, which no agent, prompt, or MCP tool ever reads. They sit on the same excluded list as email,
  `EXCLUDED_USER_FIELDS` in `app/agents/context.py`, and the module refuses to load if any of them is ever added
  to the agent profile. Accounts from before usernames kept their old email as their username, so `email` stays
  on that list too. Tests: `test_no_agent_ever_sees_the_username_or_first_name` runs all five agents, tools
  included, with a fake model that records everything it is sent and checks neither appears;
  `test_agent_profile_contains_no_pii`, `test_the_model_sees_only_goals_and_the_plan`,
  `test_the_model_never_sees_who_the_user_is` and `test_no_tool_ever_returns_username_name_or_notes` check the
  name too.
- The user is always the one in the sign-in token. Nothing the user types and nothing the model outputs
  can choose which user's data is read.
- **Calendar notes never reach any model, for any purpose.** They are the user's own words, on the same
  footing as `injury_notes`: stored in `calendar_entries.notes`, shown only to that
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

- Exercises tagged unsafe for the user's `injury_flags` (neck, shoulder, upper_back, lower_back, wrist, hip, knee,
  ankle) are removed by the SQL in `app/mcp_server/search.py: search_exercises`, which both the MCP tool and the
  plan generator use. The one list lives in `app/safety_rules.py: INJURY_FLAGS`; the quiz, the seed, the MCP tool
  and the PT's tagging template all follow it.
- **Bulk AI drafting of the imported library (decided 2026-10-24).** Every free-exercise-db exercise got drafted
  cautions in a one-time content run (`app/db/draft_injury_tags.py`, gpt-6-luna, not a live agent), under exactly the
  same rules as the hand-authored drafts: tier `ai_drafted`, source "Pending review by a licensed physical
  therapist", no citation-like text (`safety_rules.RATIONALE_CITATION_LIKE`, enforced by the generator, the seed and
  the tests, never loosened for generated content), and a caution only where one is plausible (no forced coverage).
  Anything that fails the rules after one retry stays `untagged`. Consequence, accepted on purpose: `checked_only`
  now admits almost the whole library for injured users, so their plans can include imported exercises whose
  cautions are AI drafts; the plan already labels every caution as an unreviewed draft. The token cost is logged in
  `content/exercises/source_free_exercise_db/injury_tags_generation_log.csv`, separate from `agent_runs`.
  Tests: `tests/test_bulk_injury_drafts.py`.
- **neck, upper_back and hip were added 2026-10-23, and drafted across every hand-authored exercise**, not just
  added as checkboxes: an exercise marked `draft` has been considered for every flag on the list, so adding a flag
  means drafting its tags (and their `ai_drafted` reasons) on all of them. Twelve exercises got new cautions (for
  example hip on squats, lunges and jumping; neck on crunches and Cat-Cow; upper back on rows and Superman Hold),
  all pending PT review like the rest. Test: `tests/test_new_injury_flags.py` (quiz -> stored flag -> checked_only
  -> tagged exercises out of the plan, the Workout Builder's search and the MCP tool).
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
- **No emoji (decided 2026-10-23).** The site's copy uses no decorative emoji, and neither may anything a model
  writes. The prompts ask for none, and `harness.no_emoji` strips any from every model-written text the user sees
  (Coach encouragement, Basics answers, plan explanations, Workout Builder balance notes, Workout Reviewer
  summaries). Test: `test_model_written_text_never_shows_emoji`.

**Enforced in code:** `coach.py` tone guard (a blocklist) sends a failing message back for a rewrite and
replaces it with a plain encouraging line if it still fails. The flags and the strength fun fact are
built by code from the tool results.

## 6. Building the plan (code, not the model; rewritten 2026-10-25)

Every plan comes from `app/services/program_generator.py`: plain Python, no LLM call. Same profile in, same
plan out. The quiz has ONE goal (Getting stronger, Losing weight, Just feeling good in my body). Sets, reps, rest and
session length come only from `goal_protocols` (content/protocols/goal_protocols.yaml, one row per goal x experience
level, 9 rows, PT-reviewable); the generator never invents them. The old multi-goal blending is gone.

- **Safety first.** Pregnant or postpartum (`needs_clinical_review`): no plan is generated until
  OB-GYN-reviewed guidance exists; the user is pointed to their OB-GYN or midwife. They also never reach
  ANY AI agent: the Workout Builder and Coach routes return 403, the Program Architect and Basics answer
  from code (the Basics red-flag check still runs and still logs), and the frontend sends them to
  `/pregnancy-support`. One check, `app/safety_rules.py: profile_needs_clinical_review`, decides it. Any injury flag:
  `checked_only=true` on every exercise search, no exceptions (rule 4). The injury filter applies on top of
  whichever goal is picked, unchanged: every candidate comes from the same tested SQL as the MCP tool.
- **The week is fixed by the goal**: always 4 training days (Monday, Wednesday, Friday, Saturday), built from 4 kinds
  of day: Upper body (chest, back, shoulders, arms), Lower body (legs), Mobility + core, Cardio.
  - Getting stronger: 3 strength days, each Upper OR Lower (never mixed), + 1 cardio. A 2-week block: odd weeks
    repeat the same exercises (week 1 = 3 = 5...), and even weeks repeat theirs.
  - Losing weight: 2 strength days (Upper, Lower) + 2 cardio. A 4-week block: weeks 1-4 each different, weeks 5-8
    repeat them, and so on.
  - Just feeling good: 2 mobility/core days + 1 strength day (Upper and Lower alternate) + 1 cardio. An 8-week block
    (weeks 9-16 repeat 1-8).
  - Days are 15 to 60 minutes. The protocol's session length is the cap: cardio and mobility days are circuits
    repeated to fill it (never under 15 minutes); strength days stop at 6 exercises, so with short rests (Losing
    weight) they run shorter, about 20 minutes. The plan shows each day's real estimate, not the cap.
- **What goes into a day.** A strength day hits at least two muscle groups in its category (Upper: a push and a pull,
  e.g. chest AND back; Lower: a knee-dominant and a hip-dominant move) plus at least two accessory exercises. When
  equipment or the injury filter leaves a slot empty, it falls back to the category's other groups so a day still
  reaches two groups. Each slot prefers a backbone of effective, easy-at-home moves (push-ups, band/dumbbell rows,
  overhead press, pull-aparts, curls, dips; squats, lunges, glute bridges, Romanian deadlifts, step-ups, calf raises;
  plank, dead bug, bird dog, cat-cow, hip mobility; jumping jacks, step-ups at pace, marching) matched against the real
  library, never invented ("high knees" isn't in the library, so it isn't used). These are candidate pools, not an
  override of the safety filter. Also: matched to experience level; no Olympic lifts, strongman, powerlifting or
  plyometrics on strength days; no jumping/landing moves for beginners or anyone with an injury; no pull-up-bar moves
  unless the person has a full gym.
- **The Program Architect** only explains the finished plan, from the plan, the goal, the experience level, and the
  protocol's status and citations. It has no tools and never sees weight, pregnancy status, notes, or the user id.

**Enforced in code and tested:** `tests/test_program_generator.py` (the week by goal, the repeating blocks, two muscle
groups plus two accessories, the backbone, 15-60 minutes, equipment, the injury filter for every goal and flag,
pregnancy), `tests/test_calendar_push_pull.py` (the calendar lays out exactly those days), `tests/test_plan_agent.py`
(the quiz, and the agent's inputs).

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
- Same privacy as every agent (rule 2): the model gets the computed review only, never the user's id, username,
  first name, email, weight, or any free text. Pregnant / postpartum users get a 403 before anything is computed or sent.

- **The same method, and the same rule, everywhere calories appear (2026-10-23).** Cardio logs
  (`app/services/cardio_estimate.py`: each activity type has an easier and a harder Compendium code; distance uses the
  codes that state a speed, as calories per mile; steps become distance by a rough 2,000-2,500 steps-a-mile rule of
  thumb and are labelled extra rough; "Something else" gets no number), the calorie range on each done calendar day
  (the Reviewer's per-session range for the strength minutes plus each cardio log's own range), and the progress
  marker at the top of the calendar (`app/services/progress_marker.py`) all use these calculations and only add them
  up. The progress marker has no model at all: its numbers come from `check_goal_achievement`, the calorie estimates,
  pounds = calories / 3,500 (the losing-weight goal only, labelled as a rough approximation, never a promise), and
  `compute_strength_equivalents`; its words are code templates. The full caveats are shown once, at the bottom of the
  calendar, and every figure links to them. Tests: `tests/test_calendar_redesign.py` (hand-checked numbers).

**Enforced in code:** `app/agents/workout_reviewer.py` extracts every number in the reply and compares it with the
numbers in the model's input. Any number that isn't there sends the draft back; after two tries, and once more as
a final check before returning, the reply is replaced by a plain summary written by code. A tone guard like the
Coach's applies (no shaming, guilt or food talk; it allows "calories" and "pounds", which the estimate needs), plus
no promises ("you will lose..."). Tests: `tests/test_workout_review.py`.

## 8. Weights: defaults, calibration, and going up (rewritten 2026-10-25)

- **Default starting weights** for exercises that use weights (dumbbells, kettlebells, and gym equipment), always shown
  as editable suggestions, never forced: beginner = bodyweight only (no number: the person picks); intermediate = 10 lb
  for arm (Upper body) exercises, 20 lb for leg exercises; advanced = 20 lb arms, 40 lb legs. Bodyweight and band
  exercises have no weight at all (the weight field is blank and disabled, never a made-up zero).
- **Week 1 is a calibration week.** The person logs the reps and weight they actually did. From week 2, each
  suggestion builds on the latest weight logged for that exercise (the anchor); with nothing logged, on the default.
- **How weights go up**, applied automatically from the anchor, unless the person logs a different weight (that becomes
  the new anchor, i.e. a manual override):
  - Getting stronger: up each time that exercise's day comes round again (every 2 weeks per exercise, so the plan
    gets heavier every week): +2.5 lb for arm exercises, +5 lb for leg exercises (decided with the project owner).
    Reps are the person's own call ("to failure" is their judgment during the set, not something the app computes).
  - Losing weight: +5 lb every 4 weeks, when the 4-week block starts again (weeks 5-8 are weeks 1-4, 5 lb heavier).
  - Just feeling good: no automatic increase; weights stay wherever the person sets them.
- **DECISION (2026-10-25, project owner): the goal's rule applies to everyone, including people with an injury
  flag.** This reverses the 2026-10-23 rule that held injured / rehab profiles flat. Reasoning: there's no rehab goal
  any more; the injury filter alone still decides which exercises they get (unchanged, rule 4), every weight is only a
  suggestion they can lower, and the plan keeps telling them to stop anything that hurts. Worth revisiting once a PT
  has reviewed the protocols and injury tags.
- Weeks count from `quiz_profiles.plan_started_on` (set whenever the quiz is saved; a retake is a new plan and starts
  week 1 again). Suggestions are computed live from the logs (`app/calendar.py: weight_suggestions`), not frozen in
  the calendar snapshot. Sets, reps and exercise choice never change with the weeks.

**Enforced in code:** `DEFAULT_WEIGHT_LB`, `WEIGHT_STEP_LB`, `weight_steps`, `suggested_weight` in
`app/services/program_generator.py`; `weight_suggestions` and `log_rows` in `app/calendar.py`.
Tests: `tests/test_program_generator.py` (defaults, each goal's rule, anchors), `tests/test_progression_and_modes.py`
(calibration from a real log, 5 lb after 4 weeks, feeling good stays put, beginners, injured users progress, logging
stores only real weights).

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

- **DECISION (revisited 2026-10-23, with steps, distance and calorie estimates added): pregnant / postpartum users
  can log cardio however they measure it (minutes, steps or distance), in their own words, and it counts toward their
  streak, but they get no calorie estimate and no progress marker.** Reason: logging is still just a personal record
  with no AI and no prescription, so yes to that. The numbers are different: the Compendium's MET values come from
  adults who weren't pregnant and say nothing about pregnancy or the months after birth, so the range would be less
  accurate, and calories and pound figures during pregnancy and postpartum (when weight gain or recovery is expected)
  read like weight-loss guidance, which is exactly the kind of advice we hold back until an OB-GYN has reviewed it.
  The library picker stays off for them, as above. Test: `test_pregnant_users_log_cardio_any_way_they_like_but_get_no_numbers`.
- Logging cardio on a calendar rest, open or cardio day marks that day done (it becomes a cardio day, a custom day
  that "Use my plan" can undo). Strength days are only marked done with their own toggle.

**Enforced in code:** `app/cardio.py`, `app/services/cardio_estimate.py`. Tests: `tests/test_cardio.py`,
`tests/test_calendar_redesign.py`,
(`test_pregnant_users_can_log_in_their_own_words_only`, `test_cardio_text_never_reaches_any_model`,
`test_red_flag_in_a_cardio_log_is_saved_logged_and_answered_without_ai`).

## 10. Calendar population modes, and saving Build Your Own to the calendar

- **Every day that isn't done or past offers one explicit choice (2026-10-23):** "Use my plan" (the generated day,
  where the plan has one; for a built or cardio day it brings back the planned day it replaced), "Build your own"
  (the Workout Builder, same injury filter), or "Add cardio" (a cardio day, done once cardio is logged on its date).
  Built and cardio days are custom days, so a retake keeps them. Strength days, generated or built, share the same
  done toggle; cardio days are done by logging. No AI in any of it except the Workout Builder itself. Blocked for
  pregnant / postpartum users (403), who have no plan; their activity log still works (rule 9).
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

