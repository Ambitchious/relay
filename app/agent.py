"""The tool-calling loop.

One question in, one answer out. In between the model may ask for tools; the
loop runs them, feeds the results back, and asks again. Three things make this
more than a while-loop:

1. It is *bounded*. `max_tool_iterations` caps the round trips. A model that
   keeps asking for the same tool is a real failure mode and the loop has to
   terminate on it with a usable partial answer rather than spinning.

2. Tool errors are *returned to the model*, not raised. A bad argument or a
   missing service should give the model a chance to correct itself, which it
   usually does on the next turn.

3. It records what happened — which tools ran, how many turns, how long — so
   the dashboard has something to show and the trace has something to attach.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any

from app.llm import LLMProvider, LLMResponse
from app.tools.registry import ToolRegistry

SYSTEM_PROMPT = """You are Relay, a support assistant for an internal data platform team.

You answer questions from engineers who use the platform (Spark, Airflow, Trino, Druid).

Rules:
- Use the tools to find facts. Do not answer from memory about incidents, \
metrics or runbook contents; those change, and a stale answer is worse than none.
- If a tool says there is an open incident matching the user's problem, lead with that.
- Quote the specific runbook step rather than summarising it vaguely.
- Keep answers short enough to read in a Slack message. Two or three sentences \
plus a runbook reference is usually right.
- If the tools do not have the answer, say so plainly and suggest escalating \
to the on-call engineer. Do not guess.
"""

ESCALATION_HINT = "escalat"


@dataclass
class AgentResult:
    answer: str
    tools_used: list[str] = field(default_factory=list)
    iterations: int = 0
    latency_ms: int = 0
    hit_iteration_cap: bool = False
    error: str | None = None

    @property
    def escalated(self) -> bool:
        return ESCALATION_HINT in self.answer.lower()

    @property
    def resolved(self) -> bool:
        """Answered from tool output without punting to a human.

        This is the deflection signal the dashboard reports: a request that
        was answered with evidence and did not need the on-call engineer.
        """
        return bool(self.tools_used) and not self.escalated and self.error is None


class Agent:
    def __init__(
        self,
        provider: LLMProvider,
        registry: ToolRegistry,
        max_iterations: int = 4,
        tracer: Any | None = None,
    ) -> None:
        self.provider = provider
        self.registry = registry
        self.max_iterations = max_iterations
        self.tracer = tracer

    def answer(self, question: str, *, user_id: str = "", trace_id: str = "") -> AgentResult:
        started = time.perf_counter()
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": question},
        ]
        schemas = self.registry.schemas()
        tools_used: list[str] = []
        iterations = 0
        hit_cap = False
        final_text = ""
        error: str | None = None

        span = self._span_start(question, trace_id, user_id)

        try:
            while iterations < self.max_iterations:
                iterations += 1
                response: LLMResponse = self.provider.complete(messages, schemas)

                if not response.wants_tools:
                    final_text = response.text.strip()
                    break

                messages.append(self._assistant_turn(response))

                for call in response.tool_calls:
                    output = self.registry.dispatch(call.name, call.arguments)
                    tools_used.append(call.name)
                    self._span_tool(span, call.name, call.arguments, output)
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": call.id,
                            "name": call.name,
                            "content": output,
                        }
                    )
            else:
                # Loop exhausted without the model producing a plain answer.
                hit_cap = True
                final_text = self._forced_answer(messages, schemas)

        except Exception as exc:  # noqa: BLE001 - one bad request must not kill the worker
            error = f"{type(exc).__name__}: {exc}"
            final_text = (
                "I hit an error looking that up. Please escalate to the on-call "
                "engineer if this is blocking you."
            )

        if not final_text:
            final_text = (
                "I could not find an answer in the runbooks, incidents or metrics. "
                "Suggest escalating to the on-call engineer."
            )

        result = AgentResult(
            answer=final_text,
            tools_used=tools_used,
            iterations=iterations,
            latency_ms=int((time.perf_counter() - started) * 1000),
            hit_iteration_cap=hit_cap,
            error=error,
        )
        self._span_end(span, result)
        return result

    # -- internals ---------------------------------------------------------

    def _assistant_turn(self, response: LLMResponse) -> dict[str, Any]:
        return {
            "role": "assistant",
            "content": response.text or None,
            "tool_calls": [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.name,
                        "arguments": json.dumps(call.arguments),
                    },
                }
                for call in response.tool_calls
            ],
        }

    def _forced_answer(
        self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]]
    ) -> str:
        """Ask once more with tools withheld, so the model must answer in prose.

        Without this the capped request returns nothing useful. With it the
        user gets whatever the tool output already supports, which is usually
        most of the answer.
        """
        messages = messages + [
            {
                "role": "user",
                "content": (
                    "Stop calling tools. Answer now using only what the tool "
                    "results above already tell you. If they are not enough, "
                    "say so and suggest escalating to the on-call engineer."
                ),
            }
        ]
        try:
            return self.provider.complete(messages, []).text.strip()
        except Exception:  # noqa: BLE001
            return (
                "I gathered partial information but could not finish the answer. "
                "Suggest escalating to the on-call engineer."
            )

    def _span_start(self, question: str, trace_id: str, user_id: str) -> Any:
        if self.tracer is None:
            return None
        return self.tracer.start(question=question, trace_id=trace_id, user_id=user_id)

    def _span_tool(self, span: Any, name: str, args: dict, output: str) -> None:
        if self.tracer is None or span is None:
            return
        self.tracer.tool(span, name=name, arguments=args, output=output)

    def _span_end(self, span: Any, result: AgentResult) -> None:
        if self.tracer is None or span is None:
            return
        self.tracer.end(span, result=result)
