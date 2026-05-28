# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

ChronoMind is an AI-native calendar agent. It maintains a living model of each user's goals, constraints, and progress, and continuously synchronizes their Google Calendar with that model. The project is currently in the specification phase — the service directories do not yet exist.

## Service Architecture

Five services defined in `docker-compose.yml`:

| Service | Tech | Port | Role |
|---|---|---|---|
| `frontend` | Next.js | 3000 | Dashboard UI |
| `backend` | FastAPI | 8000 | API + orchestration |
| `mcp_server` | FastMCP | 8001 | MCP tool server |
| `postgres` | PostgreSQL 16 | 5432 | Persistent state + checkpointing |
| `redis` | Redis | 6379 | Rate limiting / caching (optional) |

The `agents` service (LangGraph engine) is called internally by the backend — it is not a separate HTTP service.

## Running the Stack

```bash
docker-compose up          # Start all services
docker-compose up backend  # Start a single service
docker-compose down -v     # Tear down including volumes
```

Each service mounts its directory as a volume with hot-reload enabled (Uvicorn `--reload` for backend, Next.js dev server for frontend).

## Agent Intent Types

Every user message maps to one of seven intents handled by the LangGraph graph:

- `learn` — triggers topic planner + schedule builder (uses Tavily for curriculum fetch)
- `schedule_event` — Calendar CRUD, no planning
- `add_reminder` — zero-duration reminder event
- `lifestyle_routine` — recurring event creation
- `edit_schedule` — NL edit parser → `batch_update_events` / `batch_delete_events`
- `report_progress` — progress feedback loop, may trigger adaptive re-plan
- `query_dashboard` — aggregates from `analytics_events`

## Key State Fields

The LangGraph `AgentState` includes: `active_goals` (list), `missed_sessions`, `consecutive_session_type_count`, `deadline_at_risk`, and `user_preferences.variety_rules`. The full state is checkpointed to PostgreSQL via `langgraph-checkpoint-postgres` after every node execution.

## Backend Scheduled Jobs

A FastAPI APScheduler job runs every morning to execute the deadline guard check: `hours_remaining / available_slots_before_deadline`. If this ratio exceeds 1.0, `deadline_at_risk` flips to `True` and a recovery plan is surfaced.

## Environment Files

Each service reads its own `.env` file (e.g. `./backend/.env`, `./frontend/.env`, `./mcp_server/.env`). These are not committed. The PostgreSQL credentials in `docker-compose.yml` are `chronomind/chronomind/chronomind` (user/password/db) — development only.

## Python Setup

Requires Python 3.11+. The root `pyproject.toml` is a stub; actual dependencies will live in each service's own requirements or pyproject file.
