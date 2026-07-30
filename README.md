# AI Executive Email Assistant (AEEA)

Monorepo for the AI Executive Email Assistant.

- **`backend/`** — FastAPI application. See
  [`backend/README.md`](backend/README.md) for setup, configuration, and the
  quality gates.
- **`infra/`** — Docker Compose stack (PostgreSQL + migrations + API).
- **`frontend/`** — Next.js client (future phase, not yet started).

## Run the backend locally

```bash
docker compose -f infra/docker-compose.yml up --build
# API on http://localhost:8000  (docs at /docs)
```

## Status

Google OAuth2/Gmail integration, the full LangGraph email-triage AI agent
(categorization, priority scoring, deadline detection, task extraction,
reply drafting, calendar suggestions), long-term memory with embeddings and
decay, an editable tone-aware Draft Reply Engine, and APScheduler-driven
reminders/Google Calendar sync are all implemented. `backend/README.md` was
written incrementally per phase and may lag the code in places; the app
itself (`backend/app`) and its test suite are the source of truth.
