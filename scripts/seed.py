"""Populate the request log so the dashboard has something to show.

Runs the real agent against the real tools using the offline DemoProvider, so
the latencies, tool counts and deflection numbers come from the actual code
path rather than being invented.

    python -m scripts.seed
"""

from __future__ import annotations

import random
import time

from app.agent import Agent
from app.config import settings
from app.llm import DemoProvider
from app.store import RequestRecord, Store
from app.tools.registry import registry
import app.tools  # noqa: F401  (registers the tools)

QUESTIONS = [
    "why is spark slow today",
    "is there a known incident with airflow",
    "how do I fix executor out of memory",
    "trino queries are being rejected, is this known",
    "how do I request access to production trino",
    "my notebook kernel keeps dying",
    "is druid healthy",
    "what is the success rate on spark right now",
    "airflow dags are starting late, is that a known issue",
    "how do I raise shuffle partitions",
    "who do I ask about a quota increase",
    "is the platform down",
    "what is the p95 query duration on trino",
    "scheduler heartbeat lag is high, what do I do",
    "how long does production access take",
    # Deliberately outside the corpus. These should miss and escalate, so the
    # deflection rate on the dashboard is a real number rather than 100%.
    "can someone reset my VPN password",
    "what is the oncall rotation for the networking team",
    "how do I expense a conference ticket",
]


def main() -> None:
    store = Store(settings.db_path)
    agent = Agent(DemoProvider(), registry, max_iterations=settings.max_tool_iterations)

    now = time.time()
    written = 0

    for index, question in enumerate(QUESTIONS * 3):
        result = agent.answer(question, user_id=f"U{100 + index % 7}")

        record = RequestRecord(
            channel="C_PLATFORM_SUPPORT",
            user_id=f"U{100 + index % 7}",
            question=question,
            # Spread the rows over the last 24 hours so the volume chart has
            # a shape instead of one spike.
            created_at=now - random.uniform(0, 24 * 3600),
        )
        record.answer = result.answer
        record.tools_used = result.tools_used
        record.iterations = result.iterations
        record.latency_ms = result.latency_ms
        record.resolved = result.resolved
        record.escalated = result.escalated
        record.error = result.error
        store.save(record)
        written += 1

    print(f"seeded {written} requests into {settings.db_path}")
    print(f"total rows now: {store.count()}")


if __name__ == "__main__":
    main()
