"""Langfuse tracing, with a no-op fallback.

Observability that can take the app down is worse than no observability, so
every call here is wrapped: if Langfuse is not configured, or the SDK is not
installed, or the network is unavailable, tracing silently becomes a no-op and
the request still gets answered.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class NullTracer:
    """Used whenever tracing is off. Same interface, does nothing."""

    enabled = False

    def start(self, **_: Any) -> Any:
        return None

    def tool(self, _span: Any, **__: Any) -> None:
        return None

    def end(self, _span: Any, **__: Any) -> None:
        return None


class LangfuseTracer:
    """Thin wrapper over the Langfuse SDK.

    One trace per question. Each tool call becomes a child span carrying its
    arguments and output, so a bad answer can be read back as: which tools did
    it call, what did they return, and what did it do with that.
    """

    enabled = True

    def __init__(self, public_key: str, secret_key: str, host: str) -> None:
        from langfuse import Langfuse

        self._client = Langfuse(
            public_key=public_key, secret_key=secret_key, host=host
        )

    def start(self, *, question: str, trace_id: str = "", user_id: str = "") -> Any:
        try:
            return self._client.trace(
                name="relay.answer",
                input={"question": question},
                user_id=user_id or None,
                metadata={"slack_trace_id": trace_id} if trace_id else None,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse trace start failed: %s", exc)
            return None

    def tool(self, span: Any, *, name: str, arguments: dict, output: str) -> None:
        if span is None:
            return
        try:
            span.span(
                name=f"tool.{name}",
                input=arguments,
                output=output[:4000],
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse tool span failed: %s", exc)

    def end(self, span: Any, *, result: Any) -> None:
        if span is None:
            return
        try:
            span.update(
                output={"answer": result.answer},
                metadata={
                    "tools_used": result.tools_used,
                    "iterations": result.iterations,
                    "latency_ms": result.latency_ms,
                    "hit_iteration_cap": result.hit_iteration_cap,
                    "resolved": result.resolved,
                    "escalated": result.escalated,
                    "error": result.error,
                },
            )
            self._client.flush()
        except Exception as exc:  # noqa: BLE001
            log.warning("langfuse trace end failed: %s", exc)


def build_tracer(settings: Any) -> Any:
    if not settings.tracing_enabled:
        return NullTracer()
    try:
        return LangfuseTracer(
            settings.langfuse_public_key,
            settings.langfuse_secret_key,
            settings.langfuse_host,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("langfuse unavailable, tracing disabled: %s", exc)
        return NullTracer()
