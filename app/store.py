"""SQLite request log.

Every question the agent handles writes one row. The dashboard reads only from
here, which keeps the measurement path independent of Langfuse: if tracing is
switched off or the Langfuse account expires, the operational numbers survive.
"""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterator

SCHEMA = """
CREATE TABLE IF NOT EXISTS requests (
    id              TEXT PRIMARY KEY,
    created_at      REAL NOT NULL,
    channel         TEXT NOT NULL,
    user_id         TEXT NOT NULL,
    question        TEXT NOT NULL,
    answer          TEXT,
    tools_used      TEXT NOT NULL DEFAULT '[]',
    iterations      INTEGER NOT NULL DEFAULT 0,
    latency_ms      INTEGER NOT NULL DEFAULT 0,
    resolved        INTEGER NOT NULL DEFAULT 0,
    escalated       INTEGER NOT NULL DEFAULT 0,
    error           TEXT
);
CREATE INDEX IF NOT EXISTS idx_requests_created_at ON requests (created_at);
"""


@dataclass
class RequestRecord:
    channel: str
    user_id: str
    question: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    created_at: float = field(default_factory=time.time)
    answer: str | None = None
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    latency_ms: int = 0
    resolved: bool = False
    escalated: bool = False
    error: str | None = None


class Store:
    def __init__(self, db_path: str) -> None:
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def save(self, record: RequestRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO requests
                    (id, created_at, channel, user_id, question, answer,
                     tools_used, iterations, latency_ms, resolved, escalated, error)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.id,
                    record.created_at,
                    record.channel,
                    record.user_id,
                    record.question,
                    record.answer,
                    json.dumps(record.tools_used),
                    record.iterations,
                    record.latency_ms,
                    int(record.resolved),
                    int(record.escalated),
                    record.error,
                ),
            )

    def recent(self, limit: int = 500) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM requests ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        out = []
        for row in rows:
            item = dict(row)
            item["tools_used"] = json.loads(item["tools_used"])
            item["resolved"] = bool(item["resolved"])
            item["escalated"] = bool(item["escalated"])
            out.append(item)
        return out

    def count(self) -> int:
        with self._connect() as conn:
            return int(conn.execute("SELECT COUNT(*) FROM requests").fetchone()[0])
