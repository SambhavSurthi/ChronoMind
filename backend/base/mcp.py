import json
  import os
  import sys
  import uuid
  from datetime import datetime, timedelta, timezone
  from typing import Any, Dict, List, Optional

  import psycopg2
  from dotenv import load_dotenv
  from fastmcp import FastMCP
  from google.auth.transport.requests import Request
  from google.oauth2.credentials import Credentials
  from googleapiclient.discovery import build
  from googleapiclient.errors import HttpError

  load_dotenv()

  mcp = FastMCP("ChronoMind MCP Server")

  # ─────────────────────────────────────────────
  # Internal helpers
  # ─────────────────────────────────────────────

  DATABASE_URL = os.getenv(
      "DATABASE_URL",
      "postgresql://chronomind:chronomind@localhost:5432/chronomind",
  )
  GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "token.json")
  TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")


  def _db():
      """Open a psycopg2 connection."""
      return psycopg2.connect(DATABASE_URL)


  def _calendar():
      """Return an authenticated Google Calendar service."""
      creds: Optional[Credentials] = None
      if os.path.exists(GOOGLE_TOKEN_PATH):
          creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH)
      if not creds or not creds.valid:
          if creds and creds.expired and creds.refresh_token:
              creds.refresh(Request())
              with open(GOOGLE_TOKEN_PATH, "w") as fh:
                  fh.write(creds.to_json())
          else:
              raise RuntimeError(
                  "No valid Google token. Complete the OAuth flow and save token.json "
                  f"at {GOOGLE_TOKEN_PATH}."
              )
      return build("calendar", "v3", credentials=creds, cache_discovery=False)


  def _ensure_schema() -> None:
      """Create tables if they don't exist (idempotent)."""
      ddl = """
      CREATE TABLE IF NOT EXISTS analytics_events (
          id          BIGSERIAL PRIMARY KEY,
          event_type  TEXT        NOT NULL,
          goal_id     TEXT,
          session_id  TEXT,
          payload     JSONB       NOT NULL DEFAULT '{}',
          occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
      CREATE TABLE IF NOT EXISTS scheduled_sessions (
          session_id      TEXT PRIMARY KEY,
          goal_id         TEXT,
          topic_id        TEXT,
          title           TEXT        NOT NULL,
          session_type    TEXT        NOT NULL,
          start_time      TIMESTAMPTZ NOT NULL,
          end_time        TIMESTAMPTZ NOT NULL,
          google_event_id TEXT,
          notes           TEXT,
          completed       BOOLEAN     NOT NULL DEFAULT FALSE,
          status          TEXT        NOT NULL DEFAULT 'scheduled',
          user_id         TEXT
      );
      CREATE TABLE IF NOT EXISTS user_profiles (
          user_id            TEXT PRIMARY KEY,
          display_name       TEXT,
          timezone           TEXT        NOT NULL DEFAULT 'UTC',
          google_calendar_id TEXT        NOT NULL DEFAULT 'primary',
          time_windows       JSONB       NOT NULL DEFAULT '[]',
          preferences        JSONB       NOT NULL DEFAULT '{}',
          created_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
          updated_at         TIMESTAMPTZ NOT NULL DEFAULT NOW()
      );
      """
      try:
          conn = _db()
          with conn:
              with conn.cursor() as cur:
                  cur.execute(ddl)
          conn.close()
      except Exception as exc:
          # DB may not be running in local dev — tools will surface the error
          print(f"[mcp] schema init skipped: {exc}", file=sys.stderr)


  _ensure_schema()


  # ─────────────────────────────────────────────────────────────────────────────
  # Google Calendar tools
  # ─────────────────────────────────────────────

  @mcp.tool()
  def create_event(
      calendar_id: str,
      summary: str,
      start: str,
      end: str,
      description: str = "",
      session_id: str = "",
  ) -> Dict[str, Any]:
      """Create a single Google Calendar event.

      Args:
          calendar_id: Calendar ID (use 'primary' for the user's default calendar).
          summary: Event title.
          start: ISO 8601 datetime string, e.g. '2025-06-01T09:00:00+05:30'.
          end: ISO 8601 datetime string.
          description: Optional event body / notes.
          session_id: ChronoMind session ID stored in extendedProperties for traceability.

      Returns:
          Created event dict with 'id', 'summary', 'start', 'end', 'htmlLink'.
      """
      try:
          svc = _calendar()
          body = {
              "summary": summary,
              "description": description,
              "start": {"dateTime": start, "timeZone": "UTC"},
              "end": {"dateTime": end, "timeZone": "UTC"},
              "extendedProperties": {"private": {"chronomind_session_id": session_id}},
          }
          event = svc.events().insert(calendarId=calendar_id, body=body).execute()
          return {
              "ok": True,
              "id": event["id"],
              "summary": event["summary"],
              "start": event["start"],
              "end": event["end"],
              "htmlLink": event.get("htmlLink", ""),
          }
      except HttpError as exc:
          return {"ok": False, "error": str(exc)}
      except RuntimeError as exc:
          return {"ok": False, "error": str(exc)}


  @mcp.tool()
  def get_event(calendar_id: str, event_id: str) -> Dict[str, Any]:
      """Fetch a single Google Calendar event by its ID.

      Args:
          calendar_id: Calendar ID.
          event_id: Google Calendar event ID.

      Returns:
          Full event dict or error.
      """
      try:
          svc = _calendar()
          event = svc.events().get(calendarId=calendar_id, eventId=event_id).execute()
          return {"ok": True, "event": event}
      except HttpError as exc:
          return {"ok": False, "error": str(exc)}
      except RuntimeError as exc:
          return {"ok": False, "error": str(exc)}


  @mcp.tool()
  def list_events(
      calendar_id: str,
      time_min: str,
      time_max: str,
      max_results: int = 50,
      query: str = "",
  ) -> Dict[str, Any]:
      """List Google Calendar events within a time range.

      Args:
          calendar_id: Calendar ID.
          time_min: ISO 8601 start bound, e.g. '2025-06-01T00:00:00Z'.
          time_max: ISO 8601 end bound.
          max_results: Maximum number of events to return (1–250).
          query: Optional free-text search query.

      Returns:
          Dict with 'events' list and 'count'.
      """
      try:
          svc = _calendar()
          params: Dict[str, Any] = {
              "calendarId": calendar_id,
              "timeMin": time_min,
              "timeMax": time_max,
              "maxResults": min(max(max_results, 1), 250),
              "singleEvents": True,
              "orderBy": "startTime",
          }
          if query:
              params["q"] = query
          result = svc.events().list(**params).execute()
          events = result.get("items", [])
          return {"ok": True, "events": events, "count": len(events)}
      except HttpError as exc:
          return {"ok": False, "error": str(exc)}
      except RuntimeError as exc:
          return {"ok": False, "error": str(exc)}


  @mcp.tool()
  def update_event(
      calendar_id: str,
      event_id: str,
      summary: Optional[str] = None,
      start: Optional[str] = None,
      end: Optional[str] = None,
      description: Optional[str] = None,
  ) -> Dict[str, Any]:
      """Update fields on an existing Google Calendar event (patch semantics).

      Args:
          calendar_id: Calendar ID.
          event_id: Google Calendar event ID.
          summary: New title (omit to keep existing).
          start: New ISO 8601 start datetime (omit to keep existing).
          end: New ISO 8601 end datetime (omit to keep existing).
          description: New description (omit to keep existing).

      Returns:
          Updated event dict or error.
      """
      try:
          svc = _calendar()
          patch: Dict[str, Any] = {}
          if summary is not None:
              patch["summary"] = summary
          if start is not None:
              patch["start"] = {"dateTime": start, "timeZone": "UTC"}
          if end is not None:
              patch["end"] = {"dateTime": end, "timeZone": "UTC"}
          if description is not None:
              patch["description"] = description
          if not patch:
              return {"ok": False, "error": "No fields to update."}
          event = svc.events().patch(calendarId=calendar_id, eventId=event_id, body=patch).execute()
          return {
              "ok": True,
              "id": event["id"],
              "summary": event["summary"],
              "start": event["start"],
              "end": event["end"],
          }
      except HttpError as exc:
          return {"ok": False, "error": str(exc)}
      except RuntimeError as exc:
          return {"ok": False, "error": str(exc)}


  @mcp.tool()
  def delete_event(calendar_id: str, event_id: str) -> Dict[str, Any]:
      """Delete a Google Calendar event.

      Args:
          calendar_id: Calendar ID.
          event_id: Google Calendar event ID.

      Returns:
          {'ok': True} on success or error dict.
      """
      try:
          svc = _calendar()
          svc.events().delete(calendarId=calendar_id, eventId=event_id).execute()
          return {"ok": True, "deleted_event_id": event_id}
      except HttpError as exc:
          return {"ok": False, "error": str(exc)}
      except RuntimeError as exc:
          return {"ok": False, "error": str(exc)}


  @mcp.tool()
  def batch_create_events(
      calendar_id: str,
      events_json: str,
  ) -> Dict[str, Any]:
      """Create multiple Google Calendar events in one call.

      Args:
          calendar_id: Calendar ID.
          events_json: JSON array of event objects, each with keys:
              summary (str), start (ISO str), end (ISO str),
              description (str, optional), session_id (str, optional).

      Returns:
          Dict with 'created' list and 'failed' list.
      """
      try:
          events: List[Dict[str, Any]] = json.loads(events_json)
      except json.JSONDecodeError as exc:
          return {"ok": False, "error": f"Invalid JSON: {exc}"}

      created, failed = [], []
      for ev in events:
          result = create_event(
              calendar_id=calendar_id,
              summary=ev.get("summary", "Untitled"),
              start=ev["start"],
              end=ev["end"],
              description=ev.get("description", ""),
              session_id=ev.get("session_id", ""),
          )
          if result.get("ok"):
              created.append(result)
          else:
              failed.append({"input": ev, "error": result.get("error")})

      return {"ok": True, "created": created, "failed": failed, "total": len(events)}


  @mcp.tool()
  def batch_update_events(
      calendar_id: str,
      updates_json: str,
  ) -> Dict[str, Any]:
      """Update multiple Google Calendar events.

      Args:
          calendar_id: Calendar ID.
          updates_json: JSON array of update objects, each with:
              event_id (str, required), and any of:
              summary, start, end, description.

      Returns:
          Dict with 'updated' list and 'failed' list.
      """
      try:
          updates: List[Dict[str, Any]] = json.loads(updates_json)
      except json.JSONDecodeError as exc:
          return {"ok": False, "error": f"Invalid JSON: {exc}"}

      updated, failed = [], []
      for upd in updates:
          event_id = upd.get("event_id")
          if not event_id:
              failed.append({"input": upd, "error": "Missing event_id"})
              continue
          result = update_event(
              calendar_id=calendar_id,
              event_id=event_id,
              summary=upd.get("summary"),
              start=upd.get("start"),
              end=upd.get("end"),
              description=upd.get("description"),
          )
          if result.get("ok"):
              updated.append(result)
          else:
              failed.append({"event_id": event_id, "error": result.get("error")})

      return {"ok": True, "updated": updated, "failed": failed}


  @mcp.tool()
  def batch_delete_events(
      calendar_id: str,
      event_ids_json: str,
  ) -> Dict[str, Any]:
      """Delete multiple Google Calendar events.

      Args:
          calendar_id: Calendar ID.
          event_ids_json: JSON array of event ID strings, e.g. '["id1","id2"]'.

      Returns:
          Dict with 'deleted_count' and 'failed' list.
      """
      try:
          event_ids: List[str] = json.loads(event_ids_json)
      except json.JSONDecodeError as exc:
          return {"ok": False, "error": f"Invalid JSON: {exc}"}

      deleted, failed = 0, []
      for eid in event_ids:
          result = delete_event(calendar_id=calendar_id, event_id=eid)
          if result.get("ok"):
              deleted += 1
          else:
              failed.append({"event_id": eid, "error": result.get("error")})

      return {"ok": True, "deleted_count": deleted, "failed": failed}


  @mcp.tool()
  def find_free_slots(
      calendar_id: str,
      date_from: str,
      date_to: str,
      duration_minutes: int = 90,
      window_start_hour: int = 8,
      window_end_hour: int = 22,
  ) -> Dict[str, Any]:
      """Find free time slots in a Google Calendar within daily time windows.

      Args:
          calendar_id: Calendar ID.
          date_from: Start date, ISO format 'YYYY-MM-DD'.
          date_to: End date (inclusive), ISO format 'YYYY-MM-DD'.
          duration_minutes: Minimum slot length required (default 90).
          window_start_hour: Earliest hour to consider each day (0–23, default 8).
          window_end_hour: Latest hour to consider each day
