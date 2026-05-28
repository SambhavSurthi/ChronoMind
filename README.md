# ChronoMind — Complete Project Specification

## Complete project description

### What ChronoMind is

ChronoMind is a universal, AI-native calendar agent — not a productivity app with AI bolted on. The core idea is that every person's calendar is a reflection of their life's current priorities, and those priorities shift daily. ChronoMind maintains a living model of each user's goals, constraints, and progress, and continuously keeps their Google Calendar synchronized with that model.

### The generic user model

Rather than hard-coding student/employee/CEO personas, ChronoMind uses a fully dynamic persona system. Every user is modelled as a combination of three things: their time windows (when they're available), their goal types (learn / work / routine / social / reminder), and their session preferences (how long, what kind). The agent infers a persona softly from conversation and uses it to tune planning defaults, but never restricts what a user can do.

This means a grandmother planning daily meditation, a CEO managing 12 meetings a day, and a student learning ML all use the exact same agent graph — they just produce very different Calendar output.

### Intent types the agent handles

Every message from any user maps to one of these intents:

`learn` — "I want to learn X in N days." Triggers topic planner + schedule builder with curriculum fetch via Tavily.

`schedule_event` — "Schedule a meeting with Priya at 3pm Thursday." Pure Calendar CRUD, no planning needed.

`add_reminder` — "Remind me it's Ravi's birthday on the 14th, and to wish him at 10am." Creates a reminder-only zero-duration event.

`lifestyle_routine` — "Every morning 5–6am meditation, 8–9am cooking." Creates recurring events for the defined routine.

`edit_schedule` — "Move all my ML sessions this week to evenings." NL edit parser extracts the filter + transformation and runs batch_update_events.

`report_progress` — "I finished today's ML session" or "I skipped practice." Triggers the progress feedback loop and potentially re-plan.

`query_dashboard` — "How many hours of ML have I done this week?" Queries analytics_events and returns aggregated stats.

### The 7 standout enhancements (fully integrated)

**Adaptive re-planning**: `missed_sessions` in state is incremented every time the user reports a skip. After 2, the adaptive re-planner node redistributes the backlog across remaining days automatically, then posts a message asking whether to extend the deadline or compress. This runs without the user having to ask.

**Topic-aware session design**: The topic planner assigns a `difficulty` score (1–5) to every topic fetched from the curriculum. The schedule builder reads this and maps it to session duration — difficulty 1–2 topics get 1.5hr slots, difficulty 4–5 get 3hr+ and are placed on Saturday/Sunday or during the longest available free window that day.

**Multi-goal balancing**: `active_goals` in state is a list, not a single goal. The priority manager computes `priority_score` for each goal as a function of urgency (user-declared), days until deadline, and percentage remaining. Time allocation across goals each day is proportional to these scores.

**Session variety enforcement**: The schedule builder maintains a `consecutive_session_type_count` counter in state. After 3 lectures it forces the next slot to be a practice or revision session. The variety rules are stored per-user in `user_preferences.variety_rules` so they can be customised.

**Integrated dashboard**: The Next.js dashboard queries a `/dashboard/{user_id}` FastAPI endpoint that aggregates from `analytics_events` and `scheduled_sessions`. It shows: hours invested per goal this week, streak health (days on track), upcoming schedule for the next 7 days, completed topics per goal, and projected completion dates. All of this updates in real time as the agent creates/updates events.

**Smart NL edits**: The NL edit parser node uses a structured extraction prompt to parse the user's edit intent into a filter (`goal`, `week`, `day`, `session_type`) and a transformation (`move_to_time`, `reduce_duration`, `cancel`, `reschedule_to_day`). It then constructs the appropriate `batch_update_events` or `batch_delete_events` MCP calls without requiring the user to specify event IDs.

**Deadline guard**: After every schedule mutation (create, update, delete), the conflict resolver runs a check: `hours_remaining / available_slots_before_deadline`. If the ratio exceeds 1.0, `deadline_at_risk` flips to `True`, the agent immediately surfaces a recovery plan (extend deadline, increase daily hours, drop lower-priority topics), and the user picks one. This check also runs proactively every morning via a FastAPI scheduled job (APScheduler).

### Persistent chat memory

Every message is written to `chat_messages` with its `thread_id`. The LangGraph PostgreSQL checkpointer (using the `langgraph-checkpoint-postgres` package) persists the full graph state after every node execution. When a user returns after a week, the entire `AgentState` is rehydrated — all active goals, time preferences, session preferences, and the current schedule — so the conversation continues with full context.

### Dashboard specification

The integrated dashboard in Next.js has four panels:

The activity panel shows a bar chart of hours logged per goal per day for the past 7 days (sourced from `analytics_events`).

The goals panel shows each active goal as a card with a progress ring, days remaining to deadline, streak health indicator (green/amber/red), and the next 3 scheduled sessions.

The upcoming panel shows a week-view timeline of all scheduled sessions, colour-coded by goal, with session type badges (lecture / practice / review / meeting / routine).

The stats panel shows aggregate numbers: total hours this week across all goals, longest streak, next deadline, and the most at-risk goal.

### Docker Compose service layout

```yaml
services:
  frontend:     # Next.js — port 3000
  backend:      # FastAPI — port 8000
  agents:       # LangGraph engine — called internally by backend
  mcp_server:   # FastMCP — port 8001
  postgres:     # PostgreSQL 16 — port 5432
  redis:        # Optional — for rate limiting / caching — port 6379
```