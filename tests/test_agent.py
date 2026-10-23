"""Agent loop behaviour.

These are the tests that justify the loop existing at all: what it does when
the model misbehaves. All of them run against FakeProvider, so none of them
touch the network.
"""

from __future__ import annotations

from app.agent import Agent
from app.llm import FakeProvider, LLMResponse, ToolCall
from app.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    reg = ToolRegistry()

    @reg.register(
        name="get_status",
        description="status of a service",
        parameters={
            "type": "object",
            "properties": {"service": {"type": "string"}},
            "required": ["service"],
        },
    )
    def get_status(service: str) -> str:
        return f"{service} is degraded: success rate 97.4%"

    return reg


def test_answers_directly_when_no_tool_is_needed():
    provider = FakeProvider([LLMResponse(text="Platform docs are at go/data.")])
    result = Agent(provider, _registry()).answer("where are the docs?")

    assert result.answer == "Platform docs are at go/data."
    assert result.tools_used == []
    assert result.iterations == 1
    assert result.resolved is False, "no tool evidence means it is not a deflection"


def test_runs_a_tool_then_answers_from_its_output():
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("c1", "get_status", {"service": "spark"})]),
            LLMResponse(text="Spark is degraded at 97.4% success rate."),
        ]
    )
    result = Agent(provider, _registry()).answer("is spark ok?")

    assert result.tools_used == ["get_status"]
    assert result.iterations == 2
    assert result.resolved is True
    assert "97.4" in result.answer


def test_tool_output_is_fed_back_to_the_model():
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("c1", "get_status", {"service": "spark"})]),
            LLMResponse(text="done"),
        ]
    )
    Agent(provider, _registry()).answer("is spark ok?")

    second_turn = provider.calls[1]
    tool_messages = [m for m in second_turn if m["role"] == "tool"]
    assert len(tool_messages) == 1
    assert "97.4" in tool_messages[0]["content"]
    assert tool_messages[0]["tool_call_id"] == "c1"


def test_iteration_cap_stops_a_model_that_will_not_stop_calling_tools():
    max_iterations = 3
    # The model asks for a tool on every turn and never settles on an answer.
    looping = [
        LLMResponse(tool_calls=[ToolCall(f"c{i}", "get_status", {"service": "spark"})])
        for i in range(max_iterations)
    ]
    # The loop then makes one extra call with tools withheld, forcing prose.
    looping.append(LLMResponse(text="Partial: spark is degraded."))
    provider = FakeProvider(looping)

    result = Agent(provider, _registry(), max_iterations=max_iterations).answer("is spark ok?")

    assert result.hit_iteration_cap is True
    assert result.iterations == 3
    assert len(result.tools_used) == 3
    assert result.answer == "Partial: spark is degraded."


def test_bad_tool_name_is_returned_to_the_model_rather_than_raised():
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("c1", "does_not_exist", {})]),
            LLMResponse(text="I could not look that up."),
        ]
    )
    result = Agent(provider, _registry()).answer("anything")

    assert result.error is None, "a bad tool name is a model mistake, not a crash"
    tool_msg = [m for m in provider.calls[1] if m["role"] == "tool"][0]
    assert tool_msg["content"].startswith("Error: no tool named")


def test_bad_arguments_are_returned_to_the_model():
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("c1", "get_status", {"wrong": "x"})]),
            LLMResponse(text="Could not check that."),
        ]
    )
    Agent(provider, _registry()).answer("is spark ok?")

    tool_msg = [m for m in provider.calls[1] if m["role"] == "tool"][0]
    assert "wrong arguments" in tool_msg["content"]


def test_provider_exception_is_contained_and_reported():
    class Exploding:
        def complete(self, messages, tools):
            raise ConnectionError("groq unreachable")

    result = Agent(Exploding(), _registry()).answer("is spark ok?")

    assert result.error is not None
    assert "ConnectionError" in result.error
    assert result.escalated is True, "an errored request should point at a human"
    assert result.resolved is False


def test_escalation_is_detected_from_the_answer_text():
    provider = FakeProvider(
        [
            LLMResponse(tool_calls=[ToolCall("c1", "get_status", {"service": "spark"})]),
            LLMResponse(text="I cannot tell from this. Please escalate to the on-call engineer."),
        ]
    )
    result = Agent(provider, _registry()).answer("is spark ok?")

    assert result.escalated is True
    assert result.resolved is False, "escalated requests are not deflections"


def test_empty_model_response_falls_back_to_a_usable_message():
    provider = FakeProvider([LLMResponse(text="   ")])
    result = Agent(provider, _registry()).answer("?")

    assert result.answer
    assert "escalat" in result.answer.lower()


def test_latency_is_recorded():
    provider = FakeProvider([LLMResponse(text="ok")])
    result = Agent(provider, _registry()).answer("hi")
    assert result.latency_ms >= 0
