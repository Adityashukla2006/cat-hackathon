# CLAUDE.md

Guidance for Claude Code when working in this repository. Read this file fully before starting any task.

## Project overview

Shadow Shift is an agentic operator assistant for CAT machinery, built for a hackathon.

Before each shift, a prediction engine simulates the operator's expected shift (cycle times, fuel burn, idle windows, risk points) from past telemetry, weather, site conditions, and operator history. During the shift, the real machine runs alongside this "shadow", and meaningful gaps between the two drive agent actions.

Core components:

- **Shadow engine**: LightGBM quantile models (10th, 50th, 90th percentiles) for task time, plus regressors for expected idle and fuel.
- **Agents (LangGraph)**:
  - Planner: builds the shadow timeline, scores task risk, writes the pre-shift briefing.
  - Sentinel: deviation checks, safety rules, fatigue score, unbuckled-seatbelt-with-engine-on prompt. Deterministic Python only, no LLM calls.
  - Dispatcher: risk-aware task reordering with a one-line explanation.
  - Scribe: voice transcription, then conversion to a structured incident report.
  - Coach: personalized training recommendations, drills, instructor booking.
  - Assistant: the floating chatbot, with tools for live shift data, hazards, and guide retrieval.
- **Living Site Memory**: incidents become geofenced hazard pins that warn approaching machines and decay unless reconfirmed.
- **Training hub**: teaches operators how to use the equipment. Curriculum lessons with quizzes, a 2D joystick simulator, an interactive walkaround inspection, "learn from your shift" drills, and instructor booking.
- **Floating chatbot**: draggable, snaps to screen edges, remembers position, minimizes when a safety alert fires, and switches to voice-only while the machine is working.

## Stack

- Backend: Python 3.11, FastAPI, WebSockets, SQLAlchemy, LangGraph, `langchain-openai`
- ML: LightGBM, pandas, scikit-learn
- Database: Postgres (Neon in production, Docker locally)
- Frontend: React with Vite, Tailwind, `react-leaflet`
- LLM: OpenAI API, using structured outputs for every agent response that the code parses
- Tests: `pytest` for the backend, `vitest` with React Testing Library for the frontend
- Deploy: backend on Render, frontend on Vercel

## Repository structure

```
shadow-shift/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI app, routes, WebSocket
│   │   ├── config.py          # settings loaded from environment variables
│   │   ├── db.py              # SQLAlchemy models and session
│   │   ├── schemas.py         # Pydantic API contracts
│   │   ├── replay.py          # streams telemetry at 60x speed
│   │   ├── shadow/            # model loading and shift prediction
│   │   ├── agents/            # planner, sentinel, dispatcher, scribe, coach, assistant
│   │   ├── graph.py           # LangGraph orchestration
│   │   ├── site_memory.py     # hazard pins, geofence checks, decay
│   │   └── llm.py             # the single OpenAI client wrapper
│   ├── data/generate.py       # synthetic data generator
│   ├── guides/                # equipment how-to guides (markdown)
│   ├── ml/train.py            # trains quantile models
│   ├── tests/
│   │   ├── unit/
│   │   └── integration/       # test_phase_1.py, test_phase_2.py, ...
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/             # Tablet, Training, Supervisor
│   │   ├── components/        # SiteMap, ChatWidget, JoystickSim, Walkaround, ...
│   │   └── lib/               # API client, WebSocket hook
│   └── src/__tests__/
├── scripts/git-hooks/commit-msg
├── docker-compose.yml
└── CLAUDE.md
```

## Commands

```bash
# one-time setup: enable the commit message hook
git config core.hooksPath scripts/git-hooks
chmod +x scripts/git-hooks/commit-msg

# local services
docker compose up -d db

# backend
cd backend
pip install -r requirements.txt
python data/generate.py --seed 42
python ml/train.py
uvicorn app.main:app --reload
pytest tests/unit
pytest tests/integration

# frontend
cd frontend
npm install
npm run dev
npm test
```

## Environment variables

Stored in `.env` files that are never committed. Keep `.env.example` up to date whenever a variable is added.

- `OPENAI_API_KEY`
- `DATABASE_URL`
- `FRONTEND_ORIGIN`
- `VITE_API_URL` (frontend)

Never print, log, hardcode, or commit an API key or connection string.

## Workflow: one feature at a time

For every feature, follow this loop in order:

1. Implement the feature, keeping the change focused on that one feature.
2. Write unit tests for it in the same change.
3. Run the full unit test suite for the affected side (backend or frontend).
4. Fix anything that fails. Never commit with failing tests.
5. Commit the feature (see Git rules).

At the end of every phase:

1. Write the phase integration test file (`backend/tests/integration/test_phase_N.py`).
2. Run all unit tests and all integration tests written so far.
3. Commit the integration tests.
4. Tag the commit: `git tag phase-N`.

A phase is not complete until its integration tests pass. Do not start the next phase before that.

## Git rules

- Commit after every feature. One feature per commit.
- Commit messages are a single short line in Conventional Commits style: `type: description`
  - Allowed types: `feat`, `fix`, `test`, `refactor`, `chore`, `docs`, `style`
  - Lowercase, imperative mood, no trailing period, 60 characters or fewer
  - Examples: `feat: add replay engine`, `test: add phase 2 integration tests`, `fix: handle empty hazard list`
- Do not add a commit body unless the user asks for one.
- Never add `Co-Authored-By` trailers, "Generated with Claude Code" lines, `Claude-Session` lines, or any other attribution to commits or pull requests.
- Never commit `.env` files, model binaries larger than 5 MB, or `node_modules`.
- Never force push, rewrite pushed history, or commit directly after a failing test run.

## Testing rules

- Every feature gets unit tests. No exceptions.
- Unit tests never call the real OpenAI API. Mock the wrapper in `app/llm.py`.
- Unit tests never depend on a live database. Use a SQLite in-memory session or fixtures.
- Integration tests may use the Docker Postgres database but still mock OpenAI, so they are free and deterministic.
- Use a fixed random seed (42) for all synthetic data and model training in tests.
- Frontend components get tests for rendering and key interactions (for example, the chat widget drags, snaps to an edge, and minimizes on an alert).

## Coding conventions

- Python: type hints everywhere, Pydantic models for all request and response shapes, format with `ruff`.
- All OpenAI calls go through `app/llm.py`. No other module imports the OpenAI SDK directly.
- Every LLM response the code parses uses structured outputs with a Pydantic schema.
- Safety-critical logic (Sentinel rules, geofence checks, fatigue score) is deterministic Python, never an LLM call.
- The assistant chatbot answers safety questions only from the guides in `backend/guides/`. If the guides do not cover it, it tells the operator to stop and contact the supervisor instead of guessing.
- The demo shift must be deterministic: same seed, same scripted incidents at the same minutes, and cached LLM outputs for drills and briefings.
- Keep the operator UI glove-friendly: large touch targets, high contrast, minimal text.

## Phases, features, and integration checks

Each bullet under "Features" is one commit with its own unit tests.

### Phase 0: Setup and contracts
Features:
- repo scaffold, Docker Compose, `.env.example`
- database schema and models
- Pydantic API contracts and WebSocket message types
- OpenAI client wrapper with mocking support

Integration check: the app starts, connects to the database, creates all tables, and the health endpoint returns OK.

### Phase 1: Foundations
Features:
- synthetic data generator with the scripted demo shift
- quantile model training and backtest metric
- shadow prediction service
- replay engine at 60x speed
- telemetry WebSocket
- tablet layout with shadow timeline and ahead/behind bar
- equipment guides
- joystick simulator arm kinematics

Integration check: generated data trains the models, a prediction returns a valid range, and the replay streams telemetry over the WebSocket in order.

### Phase 2: Agents
Features:
- LangGraph orchestrator
- Planner with risk scoring and pre-shift briefing
- Sentinel rules and deviation checks
- fatigue score
- Dispatcher replanning
- Scribe voice to incident report
- alert UI and voice button
- simulator tasks and scoring
- walkaround inspection

Integration check: replaying the demo shift triggers the seatbelt prompt, the idle deviation alert, a replan, and a stored incident report at the scripted minutes.

### Phase 3: Site memory, chatbot, and training
Features:
- hazard pins with geofence and decay
- site map UI with two machines
- guide retrieval (vector store)
- assistant chatbot agent and tools
- floating chat widget
- training hub curriculum and lessons with quizzes
- learn-from-your-shift drills
- Coach recommendations
- instructor booking (mocked calendar)
- supervisor console
- handover briefing

Integration check: a hazard logged by one machine warns the second machine on approach, the chatbot answers a question using live shift data, and the Coach recommends a module that matches the operator's recorded behavior.

### Phase 4: Deployment
Features:
- Render and Vercel configuration
- production CORS and WebSocket settings
- cached demo LLM outputs

Integration check: the full demo shift runs against the deployed backend with no errors.

### Phase 5: Demo hardening
Bug fixes only, each as its own `fix:` commit. No new features in this phase.
