"""Dashboard statistics and store round-trip."""

from __future__ import annotations

import time

from app.dashboard import compute_stats, render
from app.store import RequestRecord, Store


def _row(**kw):
    base = {
        "created_at": time.time(),
        "latency_ms": 100,
        "resolved": True,
        "escalated": False,
        "error": None,
        "tools_used": ["search_runbooks"],
    }
    base.update(kw)
    return base


def test_empty_stats_do_not_divide_by_zero():
    stats = compute_stats([])
    assert stats["total"] == 0
    assert stats["deflection_pct"] == 0.0
    assert stats["p95_ms"] == 0


def test_deflection_rate_counts_resolved_over_total():
    rows = [_row(), _row(), _row(resolved=False, escalated=True), _row(resolved=False)]
    assert compute_stats(rows)["deflection_pct"] == 50.0


def test_latency_percentiles():
    rows = [_row(latency_ms=ms) for ms in (100, 200, 300, 400, 500)]
    stats = compute_stats(rows)
    assert stats["p50_ms"] == 300
    assert stats["p95_ms"] >= stats["p50_ms"]


def test_tool_counts_aggregate_across_requests():
    rows = [
        _row(tools_used=["search_runbooks", "lookup_incidents"]),
        _row(tools_used=["search_runbooks"]),
    ]
    counts = compute_stats(rows)["tool_counts"]
    assert counts["search_runbooks"] == 2
    assert counts["lookup_incidents"] == 1


def test_errors_are_counted():
    rows = [_row(), _row(error="ConnectionError: boom")]
    assert compute_stats(rows)["errors"] == 1


def test_renders_an_empty_state_without_charts():
    html = render([], tracing=False)
    assert "No requests logged yet" in html
    assert "<!doctype html>" in html


def test_renders_charts_when_there_is_data():
    html = render([_row()], tracing=True)
    assert "plotly" in html.lower()
    assert "Deflection rate" in html


def test_store_round_trip(tmp_path):
    store = Store(str(tmp_path / "t.db"))
    record = RequestRecord(channel="C1", user_id="U1", question="why is spark slow")
    record.answer = "known incident INC-4417"
    record.tools_used = ["lookup_incidents"]
    record.latency_ms = 240
    record.resolved = True
    store.save(record)

    rows = store.recent()
    assert len(rows) == 1
    assert rows[0]["question"] == "why is spark slow"
    assert rows[0]["tools_used"] == ["lookup_incidents"]
    assert rows[0]["resolved"] is True
    assert store.count() == 1
