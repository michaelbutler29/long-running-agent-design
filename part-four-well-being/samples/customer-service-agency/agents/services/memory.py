"""Memory helpers — shared infrastructure for reading/writing AgentCore Memory."""

import json
from datetime import datetime, timezone

from agents._shared import MEMORY_ID, data_client


def run_summary_session(actor_id: str) -> str:
    return f"runsummary-{actor_id}"


def session_summary_text(actor_id: str, session_id: str) -> str:
    resp = data_client.list_memory_records(
        memoryId=MEMORY_ID,
        namespace=f"/summaries/{actor_id}/{session_id}/",
        maxResults=5,
    )
    records = resp.get("memoryRecordSummaries", resp.get("memoryRecords", []))
    texts = [r.get("content", {}).get("text", "") for r in records]
    return "\n".join(t for t in texts if t)


def latest_run_summary(actor_id: str) -> str:
    """Most recent Run Summary blob checkpoint, or '' if none exists."""
    resp = data_client.list_events(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=run_summary_session(actor_id),
        maxResults=100,
    )
    events = resp.get("events", [])
    if not events:
        return ""
    latest = max(events, key=lambda e: e.get("eventTimestamp"))
    for item in latest.get("payload", []):
        if "blob" in item:
            blob = item["blob"]
            return blob if isinstance(blob, str) else json.dumps(blob)
    return ""


def run_summary_event_ids(actor_id: str) -> set[str]:
    resp = data_client.list_events(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=run_summary_session(actor_id),
        maxResults=100,
    )
    return {e.get("eventId", "") for e in resp.get("events", [])}


def put_blob_event(actor_id: str, session_id: str, blob: str) -> str:
    resp = data_client.create_event(
        memoryId=MEMORY_ID,
        actorId=actor_id,
        sessionId=session_id,
        eventTimestamp=datetime.now(timezone.utc),
        payload=[{"blob": blob}],
    )
    return resp.get("event", {}).get("eventId", "")
