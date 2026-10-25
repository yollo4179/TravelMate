"""Check confirmation and observed backend state independently of model prose."""
from __future__ import annotations

from typing import Any


def state_metrics(case: dict[str, Any], record: dict[str, Any], response: dict[str, Any]) -> dict[str, float | None]:
    expected = case["expectations"]["state"]
    if expected is None:
        return {}
    data = response.get("data")
    values: dict[str, float | None] = {
        "preview_not_reported_as_applied": float(not data.get("applied")) if isinstance(data, dict) and "applied" in data and not expected["applied"] else None,
        "observed_plan_state_preserved": None,
        "observed_nonplan_memory_preserved": None,
        "confirmation_precedes_apply": float(case["input"].get("confirmed_event", {}).get("confirmed") is True) if isinstance(data, dict) and data.get("applied") else None,
        "observed_commit_version_matches": None,
    }
    observations = record.get("observations") or {}
    if not isinstance(observations, dict):
        return values
    if observations.get("source") != "backend_observation":
        return values
    if "plan_before" in observations and "plan_after" in observations and not expected["applied"]:
        values["observed_plan_state_preserved"] = float(observations["plan_before"] == observations["plan_after"])
    if expected["applied"] and isinstance(data, dict) and "plan_before" in observations and "plan_after" in observations:
        before = observations["plan_before"].get("version")
        after = observations["plan_after"].get("version")
        values["observed_commit_version_matches"] = float(type(before) is int and type(after) is int and after == before + 1 and after == data.get("version"))
    if case["expectations"]["memory"] and case["expectations"]["memory"].get("rollback_scope") == "plan_only":
        if "nonplan_before" in observations and "nonplan_after" in observations:
            values["observed_nonplan_memory_preserved"] = float(observations["nonplan_before"] == observations["nonplan_after"])
    return values
