"""FastAPI entrypoint: Slack webhook, ask API, dashboard, healthcheck."""

from __future__ import annotations

import logging

from fastapi import BackgroundTasks, FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel

from app.agent import Agent
from app.config import settings
from app.dashboard import render
from app.llm import build_provider
from app.slack import SlackClient, extract_question, should_handle, verify_signature
from app.store import RequestRecord, Store
from app.tools.registry import registry
from app.tracing import build_tracer

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("relay")

import app.tools  # noqa: E402,F401  (registers the tools)

app = FastAPI(title="Relay", docs_url="/docs")

store = Store(settings.db_path)
tracer = build_tracer(settings)
agent = Agent(
    provider=build_provider(settings),
    registry=registry,
    max_iterations=settings.max_tool_iterations,
    tracer=tracer,
)

# Slack delivers at-least-once. Without de-duplication a retried delivery is
# answered twice in the same thread, which is the most visible way a bot can
# look broken.
_seen_events: set[str] = set()
_SEEN_CAP = 1000


def _already_handled(event_id: str) -> bool:
    if not event_id:
        return False
    if event_id in _seen_events:
        return True
    if len(_seen_events) >= _SEEN_CAP:
        _seen_events.clear()
    _seen_events.add(event_id)
    return False


def handle_question(
    question: str, channel: str, user_id: str, thread_ts: str | None, event_id: str
) -> None:
    """Run the agent, log the request, post the reply. Runs in the background."""
    record = RequestRecord(channel=channel, user_id=user_id, question=question)
    result = agent.answer(question, user_id=user_id, trace_id=event_id)

    record.answer = result.answer
    record.tools_used = result.tools_used
    record.iterations = result.iterations
    record.latency_ms = result.latency_ms
    record.resolved = result.resolved
    record.escalated = result.escalated
    record.error = result.error
    store.save(record)

    SlackClient(settings.slack_bot_token).post_message(channel, result.answer, thread_ts)


@app.get("/health")
def health() -> JSONResponse:
    return JSONResponse(
        {
            "ok": True,
            "llm": settings.llm_provider if settings.llm_enabled else "fake",
            "slack": settings.slack_enabled,
            "tracing": settings.tracing_enabled,
            "tools": registry.names(),
            "requests_logged": store.count(),
        }
    )


class AskRequest(BaseModel):
    question: str
    user_id: str = "local"


@app.post("/ask")
def ask(payload: AskRequest) -> JSONResponse:
    """Synchronous endpoint — the same path Slack takes, without Slack.

    Exists so the agent can be exercised from curl or a test without a Slack
    workspace, which is also how the seed script generates dashboard data.
    """
    record = RequestRecord(channel="api", user_id=payload.user_id, question=payload.question)
    result = agent.answer(payload.question, user_id=payload.user_id)

    record.answer = result.answer
    record.tools_used = result.tools_used
    record.iterations = result.iterations
    record.latency_ms = result.latency_ms
    record.resolved = result.resolved
    record.escalated = result.escalated
    record.error = result.error
    store.save(record)

    return JSONResponse(
        {
            "answer": result.answer,
            "tools_used": result.tools_used,
            "iterations": result.iterations,
            "latency_ms": result.latency_ms,
            "resolved": result.resolved,
            "escalated": result.escalated,
            "hit_iteration_cap": result.hit_iteration_cap,
        }
    )


@app.post("/slack/events")
async def slack_events(request: Request, background: BackgroundTasks):
    body = await request.body()

    if not verify_signature(
        settings.slack_signing_secret,
        request.headers.get("X-Slack-Request-Timestamp", ""),
        body,
        request.headers.get("X-Slack-Signature", ""),
    ):
        return PlainTextResponse("invalid signature", status_code=401)

    payload = await request.json()

    # One-time handshake when the Events API subscription is first saved.
    if payload.get("type") == "url_verification":
        return PlainTextResponse(payload.get("challenge", ""))

    event = payload.get("event") or {}
    if not should_handle(event):
        return PlainTextResponse("ignored")

    if _already_handled(payload.get("event_id", "")):
        return PlainTextResponse("duplicate")

    question = extract_question(event)
    if not question:
        return PlainTextResponse("empty")

    # Ack inside Slack's 3s window; the agent runs after the response is sent.
    background.add_task(
        handle_question,
        question,
        event.get("channel", ""),
        event.get("user", ""),
        event.get("thread_ts") or event.get("ts"),
        payload.get("event_id", ""),
    )
    return PlainTextResponse("ok")


@app.get("/", response_class=HTMLResponse)
def dashboard() -> HTMLResponse:
    return HTMLResponse(render(store.recent(), tracing=settings.tracing_enabled))
