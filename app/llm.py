"""Provider-agnostic chat/tool-call adapter.

Groq, OpenAI and Anthropic all expose "here are some tools, call one if you
need it" but disagree on the wire format. The agent loop should not care, so
each provider is normalised to a single shape:

    complete(messages, tools) -> LLMResponse(text, tool_calls, raw)

`FakeProvider` implements the same contract deterministically so the agent loop
can be tested without a network call or an API key. That matters more than it
sounds: the loop's interesting behaviour is what it does on a malformed tool
call or a model that will not stop calling tools, and neither is reproducible
against a live model.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def wants_tools(self) -> bool:
        return bool(self.tool_calls)


class LLMProvider(Protocol):
    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


# --------------------------------------------------------------------------
# OpenAI-compatible providers (Groq, OpenAI)
# --------------------------------------------------------------------------


class OpenAICompatProvider:
    """Works against any /chat/completions endpoint that speaks tool calls."""

    def __init__(self, api_key: str, model: str, base_url: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        import httpx

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0,
        }
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
            payload["tool_choice"] = "auto"

        response = httpx.post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()
        message = data["choices"][0]["message"]

        calls: list[ToolCall] = []
        for call in message.get("tool_calls") or []:
            fn = call.get("function", {})
            calls.append(
                ToolCall(
                    id=call.get("id", ""),
                    name=fn.get("name", ""),
                    # The model returns arguments as a JSON *string*. It is
                    # occasionally malformed; the agent loop handles an empty
                    # dict by telling the model it sent bad arguments.
                    arguments=_safe_json(fn.get("arguments", "{}")),
                )
            )

        return LLMResponse(text=message.get("content") or "", tool_calls=calls, raw=data)


def _safe_json(raw: str) -> dict[str, Any]:
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


# --------------------------------------------------------------------------
# Anthropic
# --------------------------------------------------------------------------


class AnthropicProvider:
    def __init__(self, api_key: str, model: str, timeout: int = 30) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        import httpx

        system = ""
        convo: list[dict[str, Any]] = []
        for msg in messages:
            if msg["role"] == "system":
                system = msg["content"]
            else:
                convo.append(msg)

        payload: dict[str, Any] = {
            "model": self.model,
            "max_tokens": 1024,
            "messages": convo,
        }
        if system:
            payload["system"] = system
        if tools:
            payload["tools"] = [
                {
                    "name": t["name"],
                    "description": t["description"],
                    "input_schema": t["parameters"],
                }
                for t in tools
            ]

        response = httpx.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": self.api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json=payload,
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json()

        text_parts: list[str] = []
        calls: list[ToolCall] = []
        for block in data.get("content", []):
            if block.get("type") == "text":
                text_parts.append(block.get("text", ""))
            elif block.get("type") == "tool_use":
                calls.append(
                    ToolCall(
                        id=block.get("id", ""),
                        name=block.get("name", ""),
                        arguments=block.get("input") or {},
                    )
                )

        return LLMResponse(text="".join(text_parts), tool_calls=calls, raw=data)


# --------------------------------------------------------------------------
# Deterministic provider for tests and offline demos
# --------------------------------------------------------------------------


class FakeProvider:
    """Scripted provider.

    Takes a list of LLMResponse objects and returns them in order, so a test
    can describe exactly the sequence of model turns it wants to exercise:
    a tool call, then another, then a final answer.
    """

    def __init__(self, script: list[LLMResponse] | None = None) -> None:
        self.script = list(script or [])
        self.calls: list[list[dict[str, Any]]] = []

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        self.calls.append(messages)
        if self.script:
            return self.script.pop(0)
        return LLMResponse(text="I don't have enough information to answer that.")


class DemoProvider:
    """Keyword-routed provider for running the whole path without an API key.

    Not a model — it picks a tool by keyword, then writes an answer from the
    tool output. It exists so the agent loop, the tools, the store and the
    dashboard can all be exercised end to end offline, which is what the seed
    script uses. Set LLM_PROVIDER=groq for real reasoning.
    """

    ROUTES: list[tuple[tuple[str, ...], str]] = [
        (("incident", "known issue", "outage", "broken", "down"), "lookup_incidents"),
        (("slow", "latency", "healthy", "health", "success rate", "queue"), "get_platform_metrics"),
    ]

    SERVICES = ("spark", "airflow", "trino", "druid")

    def __init__(self, simulate_latency: bool = True) -> None:
        # A real model call is a network round trip; this one is instant, which
        # would make the dashboard's latency tiles read 0 ms and look broken.
        # The delay is simulated and only ever applies to this demo provider.
        self.simulate_latency = simulate_latency

    def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        if self.simulate_latency:
            import random
            import time

            time.sleep(random.uniform(0.15, 0.6))

        question = next(
            (m["content"] for m in messages if m["role"] == "user" and m.get("content")), ""
        ).lower()

        tool_outputs = [m["content"] for m in messages if m.get("role") == "tool"]

        # Second pass: a tool has already run, so answer from its output.
        if tool_outputs or not tools:
            body = tool_outputs[-1] if tool_outputs else ""
            if not body or body.startswith("Error:") or "No " in body[:4]:
                return LLMResponse(
                    text=(
                        "I could not find that in the runbooks, incidents or metrics. "
                        "Suggest escalating to the on-call engineer."
                    )
                )
            first = body.strip().splitlines()[0]
            return LLMResponse(text=f"Here is what I found: {first}")

        service = next((s for s in self.SERVICES if s in question), "")
        for keywords, tool_name in self.ROUTES:
            if any(k in question for k in keywords):
                args = {"service": service} if service else {}
                if tool_name == "get_platform_metrics" and not service:
                    continue
                return LLMResponse(tool_calls=[ToolCall("demo-1", tool_name, args)])

        return LLMResponse(
            tool_calls=[ToolCall("demo-1", "search_runbooks", {"query": question})]
        )


def build_provider(settings: Any) -> LLMProvider:
    provider = settings.llm_provider
    if provider == "groq":
        return OpenAICompatProvider(
            settings.llm_api_key,
            settings.llm_model,
            "https://api.groq.com/openai/v1",
            settings.request_timeout_s,
        )
    if provider == "openai":
        return OpenAICompatProvider(
            settings.llm_api_key,
            settings.llm_model,
            "https://api.openai.com/v1",
            settings.request_timeout_s,
        )
    if provider == "anthropic":
        return AnthropicProvider(
            settings.llm_api_key, settings.llm_model, settings.request_timeout_s
        )
    if provider == "demo":
        return DemoProvider()
    return FakeProvider()
