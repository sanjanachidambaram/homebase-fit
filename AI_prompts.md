# AI Prompts Log: HomeBase Fit (Final Project)

## 2026-10-22

1. Scaffold the repo: backend (FastAPI/PydanticAI/FastMCP with prompts folder), Vite React TS frontend, README stub, .env.example, .gitignore, requirements, venv, and initial git commit (no schema, agents, or real UI yet).
2. Build the data layer: content/ folders (placeholder quiz, intro video README, 3 program templates incl. weight loss + lower back rehab, exercise media folders by muscle group, 5 Fitness Basics articles), SQLite schema with safety_events, seeded original DB + resettable working copy, seed/reset scripts, and a dev-only GET /api/debug/tables route.
3. Import free-exercise-db (876 exercises + images, Unlicense) as a second exercise source with ATTRIBUTION.md, tag the 27 originals as placeholder-authored, generate a PT contraindication-tagging CSV covering all exercises, add a source registry served at GET /api/sources, and replace the Vite template with a test page (exercise card grid with muscle-group filter + "Data & Sources" footer).
