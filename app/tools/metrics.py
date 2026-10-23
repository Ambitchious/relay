"""Platform health metrics tool — the raw operational numbers.

Reads from a local snapshot file. In a real deployment this is where a
Prometheus or Splunk query would go; the tool contract the model sees would
not change, which is the point of keeping the data source behind a tool.
"""

from __future__ import annotations

import json
from functools import lru_cache

from app.config import DATA_DIR
from app.tools.registry import registry

METRICS_FILE = DATA_DIR / "metrics.json"


@lru_cache(maxsize=1)
def _metrics() -> dict[str, dict]:
    if not METRICS_FILE.exists():
        return {}
    return json.loads(METRICS_FILE.read_text(encoding="utf-8"))


def reset_metrics() -> None:
    _metrics.cache_clear()


@registry.register(
    name="get_platform_metrics",
    description=(
        "Get current health metrics for a platform service — success rate, "
        "p95 latency, queue depth and running job count. Use this when the "
        "user asks whether a service is healthy, slow, or backed up."
    ),
    parameters={
        "type": "object",
        "properties": {
            "service": {
                "type": "string",
                "description": "Service name, e.g. 'spark', 'airflow', 'trino', 'druid'.",
            }
        },
        "required": ["service"],
    },
)
def get_platform_metrics(service: str) -> str:
    data = _metrics()
    key = (service or "").strip().lower()

    if key not in data:
        known = ", ".join(sorted(data)) or "none loaded"
        return f"No metrics for {service!r}. Known services: {known}."

    snapshot = data[key]
    parts = [f"{key} (as of {snapshot.get('as_of', 'unknown')}):"]
    for label, value in snapshot.items():
        if label == "as_of":
            continue
        parts.append(f"  {label}: {value}")

    # Flag the obvious breach rather than making the model infer a threshold
    # from a bare number; the threshold is an operational fact, not a judgement
    # the model should be guessing at.
    success = snapshot.get("success_rate_pct")
    if isinstance(success, (int, float)) and success < 99.0:
        parts.append(f"  NOTE: success rate {success}% is below the 99% SLO.")

    return "\n".join(parts)
