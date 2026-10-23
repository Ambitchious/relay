"""Incident lookup tool — answers "is this a known problem right now?"."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from app.config import DATA_DIR
from app.tools.registry import registry

INCIDENT_FILE = DATA_DIR / "incidents.json"


@lru_cache(maxsize=1)
def _incidents() -> list[dict]:
    if not INCIDENT_FILE.exists():
        return []
    return json.loads(INCIDENT_FILE.read_text(encoding="utf-8"))


def reset_incidents() -> None:
    _incidents.cache_clear()


def _within_window(opened_at: str, days: int) -> bool:
    try:
        opened = datetime.fromisoformat(opened_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    if opened.tzinfo is None:
        opened = opened.replace(tzinfo=timezone.utc)
    return opened >= datetime.now(timezone.utc) - timedelta(days=days)


@registry.register(
    name="lookup_incidents",
    description=(
        "Look up platform incidents by service name and status. Use this to "
        "check whether a problem the user is reporting is already a known "
        "open incident before suggesting they debug it themselves."
    ),
    parameters={
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": (
                    "Service to filter on, e.g. 'spark', 'airflow', 'trino'. "
                    "Omit to search all services."
                ),
            },
            "status": {
                "type": "string",
                "enum": ["open", "resolved", "any"],
                "description": "Incident status to filter on. Default 'open'.",
            },
            "days": {
                "type": "integer",
                "description": "Only include incidents opened in the last N days. Default 7.",
            },
        },
        "required": [],
    },
)
def lookup_incidents(service: str = "", status: str = "open", days: int = 7) -> str:
    service = (service or "").strip().lower()
    status = (status or "open").strip().lower()
    days = max(1, min(int(days), 90))

    matches = []
    for incident in _incidents():
        if service and service not in incident.get("service", "").lower():
            continue
        if status != "any" and incident.get("status", "").lower() != status:
            continue
        if not _within_window(incident.get("opened_at", ""), days):
            continue
        matches.append(incident)

    if not matches:
        scope = f" for {service}" if service else ""
        return f"No {status} incidents{scope} in the last {days} days."

    matches.sort(key=lambda i: i.get("opened_at", ""), reverse=True)
    lines = []
    for inc in matches[:5]:
        lines.append(
            f"{inc.get('id')} [{inc.get('severity', 'unknown')}] "
            f"{inc.get('service')} — {inc.get('title')} "
            f"(status: {inc.get('status')}, opened {inc.get('opened_at')})"
            + (f"\n  runbook: {inc['runbook']}" if inc.get("runbook") else "")
        )
    return "\n".join(lines)
