"""Operational dashboard.

Four numbers an on-call engineer would actually act on, then two charts. The
deflection rate is the headline: of the questions people asked, how many did
Relay answer from evidence without pulling in a human.

Plotly is rendered to a self-contained HTML fragment rather than a static
image so the charts stay hoverable, and the page is served by the same
FastAPI app as the webhook — one process, one deploy.
"""

from __future__ import annotations

import statistics
from collections import Counter
from datetime import datetime, timezone
from typing import Any

import plotly.graph_objects as go
from plotly.io import to_html

# Matches the muted, high-contrast look of the rest of the page; distinct hues
# rather than a gradient so the two series stay separable for colour-blind
# readers and in greyscale print.
ACCENT = "#2f6f8f"
MUTED = "#c2653a"
GRID = "rgba(0,0,0,0.08)"


def compute_stats(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    if total == 0:
        return {
            "total": 0,
            "deflection_pct": 0.0,
            "p50_ms": 0,
            "p95_ms": 0,
            "escalated": 0,
            "errors": 0,
            "tool_counts": {},
            "by_hour": {},
        }

    latencies = sorted(r["latency_ms"] for r in rows)
    resolved = sum(1 for r in rows if r["resolved"])
    escalated = sum(1 for r in rows if r["escalated"])
    errors = sum(1 for r in rows if r.get("error"))

    tool_counts: Counter[str] = Counter()
    for row in rows:
        tool_counts.update(row["tools_used"])

    by_hour: Counter[str] = Counter()
    for row in rows:
        stamp = datetime.fromtimestamp(row["created_at"], tz=timezone.utc)
        by_hour[stamp.strftime("%Y-%m-%d %H:00")] += 1

    return {
        "total": total,
        "deflection_pct": round(100 * resolved / total, 1),
        "p50_ms": int(statistics.median(latencies)),
        "p95_ms": int(latencies[max(0, int(len(latencies) * 0.95) - 1)]),
        "escalated": escalated,
        "errors": errors,
        "tool_counts": dict(tool_counts.most_common()),
        "by_hour": dict(sorted(by_hour.items())),
    }


def _layout(title: str) -> dict[str, Any]:
    return {
        "title": {"text": title, "font": {"size": 15}},
        "margin": {"l": 48, "r": 16, "t": 48, "b": 40},
        "height": 300,
        "paper_bgcolor": "rgba(0,0,0,0)",
        "plot_bgcolor": "rgba(0,0,0,0)",
        "font": {"family": "system-ui, -apple-system, sans-serif", "size": 12},
        "xaxis": {"gridcolor": GRID, "zeroline": False},
        "yaxis": {"gridcolor": GRID, "zeroline": False, "rangemode": "tozero"},
    }


def volume_chart(by_hour: dict[str, int]) -> str:
    fig = go.Figure(
        go.Scatter(
            x=list(by_hour),
            y=list(by_hour.values()),
            mode="lines+markers",
            line={"color": ACCENT, "width": 2},
            marker={"size": 6},
            hovertemplate="%{x}<br>%{y} requests<extra></extra>",
        )
    )
    fig.update_layout(**_layout("Requests per hour"))
    return to_html(fig, include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


def tools_chart(tool_counts: dict[str, int]) -> str:
    fig = go.Figure(
        go.Bar(
            x=list(tool_counts.values()),
            y=list(tool_counts),
            orientation="h",
            marker={"color": MUTED},
            hovertemplate="%{y}: %{x} calls<extra></extra>",
        )
    )
    layout = _layout("Tool calls")
    layout["yaxis"]["automargin"] = True
    fig.update_layout(**layout)
    return to_html(fig, include_plotlyjs=False, full_html=False, config={"displayModeBar": False})


PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Relay — platform support</title>
<script src="https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.27.0/plotly.min.js"></script>
<style>
  :root {{
    --bg: #faf9f7; --fg: #1c1a17; --muted: #6b655d;
    --card: #ffffff; --line: rgba(0,0,0,0.09); --accent: #2f6f8f;
  }}
  @media (prefers-color-scheme: dark) {{
    :root:not([data-theme="light"]) {{
      --bg: #16151a; --fg: #ece9e4; --muted: #9b958c;
      --card: #1f1e24; --line: rgba(255,255,255,0.10); --accent: #74b3d1;
    }}
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--fg);
    font: 15px/1.55 system-ui, -apple-system, "Segoe UI", sans-serif;
  }}
  .wrap {{ max-width: 980px; margin: 0 auto; padding: 40px 16px 64px; }}
  h1 {{ font-size: 1.5rem; margin: 0 0 4px; letter-spacing: -0.01em; }}
  .sub {{ color: var(--muted); margin: 0 0 28px; font-size: 0.92rem; }}
  .tiles {{
    display: grid; gap: 12px; margin-bottom: 28px;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  }}
  .tile {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 10px; padding: 16px 18px;
  }}
  .tile .label {{
    color: var(--muted); font-size: 0.74rem; text-transform: uppercase;
    letter-spacing: 0.06em; margin-bottom: 6px;
  }}
  .tile .value {{ font-size: 1.7rem; font-weight: 600; letter-spacing: -0.02em; }}
  .tile .value.accent {{ color: var(--accent); }}
  .card {{
    background: var(--card); border: 1px solid var(--line);
    border-radius: 10px; padding: 8px 12px; margin-bottom: 16px;
  }}
  .empty {{ color: var(--muted); padding: 36px 0; text-align: center; }}
  footer {{ color: var(--muted); font-size: 0.82rem; margin-top: 28px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>Relay</h1>
  <p class="sub">Platform support agent &middot; {total} requests logged &middot; tracing {tracing}</p>

  <div class="tiles">
    <div class="tile"><div class="label">Deflection rate</div>
      <div class="value accent">{deflection_pct}%</div></div>
    <div class="tile"><div class="label">p50 latency</div>
      <div class="value">{p50_ms} ms</div></div>
    <div class="tile"><div class="label">p95 latency</div>
      <div class="value">{p95_ms} ms</div></div>
    <div class="tile"><div class="label">Escalated</div>
      <div class="value">{escalated}</div></div>
    <div class="tile"><div class="label">Errors</div>
      <div class="value">{errors}</div></div>
  </div>

  {body}

  <footer>
    Deflection rate = answered from tool evidence without suggesting the on-call
    engineer. Latency is end-to-end, including every tool round trip.
  </footer>
</div>
</body>
</html>
"""


def render(rows: list[dict[str, Any]], *, tracing: bool) -> str:
    stats = compute_stats(rows)
    if stats["total"] == 0:
        body = '<div class="card"><p class="empty">No requests logged yet. ' \
               'Ask Relay something, or run <code>python -m scripts.seed</code>.</p></div>'
    else:
        body = (
            f'<div class="card">{volume_chart(stats["by_hour"])}</div>'
            f'<div class="card">{tools_chart(stats["tool_counts"])}</div>'
        )

    return PAGE.format(
        total=stats["total"],
        deflection_pct=stats["deflection_pct"],
        p50_ms=stats["p50_ms"],
        p95_ms=stats["p95_ms"],
        escalated=stats["escalated"],
        errors=stats["errors"],
        tracing="on" if tracing else "off",
        body=body,
    )
