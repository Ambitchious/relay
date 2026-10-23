"""Tool dispatch, argument handling and failure modes."""

from __future__ import annotations

import pytest

from app.tools.registry import ToolRegistry, registry
import app.tools  # noqa: F401  (registers the real tools)


def test_real_tools_are_registered():
    names = set(registry.names())
    assert {"search_runbooks", "lookup_incidents", "get_platform_metrics"} <= names


def test_every_schema_is_well_formed():
    for schema in registry.schemas():
        assert schema["name"]
        assert schema["description"]
        assert schema["parameters"]["type"] == "object"
        assert "properties" in schema["parameters"]


def test_unknown_tool_returns_an_error_string_not_an_exception():
    out = registry.dispatch("no_such_tool", {})
    assert out.startswith("Error:")
    assert "search_runbooks" in out, "should tell the model what it can call"


def test_wrong_arguments_are_reported_back_to_the_model():
    out = registry.dispatch("get_platform_metrics", {"wrong_kwarg": "spark"})
    assert out.startswith("Error: wrong arguments")


def test_tool_exception_is_caught_and_described():
    local = ToolRegistry()

    @local.register(name="boom", description="always fails", parameters={
        "type": "object", "properties": {}, "required": []})
    def _boom() -> str:
        raise RuntimeError("upstream down")

    out = local.dispatch("boom", {})
    assert "RuntimeError" in out and "upstream down" in out


def test_runbook_search_finds_the_spark_runbook():
    out = registry.dispatch("search_runbooks", {"query": "executor out of memory"})
    assert "spark-executor-oom" in out


def test_runbook_search_handles_a_miss():
    out = registry.dispatch("search_runbooks", {"query": "quantum teleportation"})
    assert "No runbook matched" in out


def test_incident_lookup_filters_by_service_and_status():
    out = registry.dispatch("lookup_incidents", {"service": "spark", "status": "open", "days": 90})
    assert "INC-4417" in out
    assert "INC-4412" not in out, "airflow incident should be filtered out"


def test_incident_lookup_reports_an_empty_result_clearly():
    out = registry.dispatch(
        "lookup_incidents", {"service": "nonexistent", "status": "open", "days": 90}
    )
    assert "No open incidents" in out


def test_metrics_flags_an_slo_breach():
    out = registry.dispatch("get_platform_metrics", {"service": "spark"})
    assert "97.4" in out
    assert "below the 99% SLO" in out


def test_metrics_does_not_flag_a_healthy_service():
    out = registry.dispatch("get_platform_metrics", {"service": "trino"})
    assert "below the 99% SLO" not in out


def test_metrics_unknown_service_lists_known_ones():
    out = registry.dispatch("get_platform_metrics", {"service": "mysql"})
    assert "Known services" in out and "spark" in out
