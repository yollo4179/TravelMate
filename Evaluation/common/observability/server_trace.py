"""Keep unavailable native-runtime quality observations out of score denominators."""
from __future__ import annotations

from typing import Any

from common.runs.tracks import PLAN_METRICS, STATE_METRICS, TOOL_METRICS, MEMORY_METRICS
from common.observability.search_records import is_search_api_record

NATIVE_SOURCES = frozenset({"spring_execution_mock", "spring_execution_live"})
SEARCH_PREFIXES = ("top_", "recall_at_", "precision_at_", "f1_at_", "mrr_at_", "map_at_", "ndcg_at_", "judged_at_")


def is_native_record(record: dict[str, Any]) -> bool:
    return record.get("record_source") in NATIVE_SOURCES


def message_is_observed(record: dict[str, Any]) -> bool:
    if is_search_api_record(record):
        return False
    if not is_native_record(record):
        return True
    return (record.get("execution_mode") == "LIVE"
            and record.get("observation_coverage", {}).get("message") is True)


def mask_unobserved(metrics: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    if not is_native_record(record):
        return metrics
    coverage = record.get("observation_coverage") or {}
    live = record.get("execution_mode") == "LIVE"
    groups = {
        **{name: "tool_call" for name in TOOL_METRICS},
        **{name: "plan" for name in PLAN_METRICS},
        **{name: "state" for name in STATE_METRICS},
        **{name: "memory" for name in MEMORY_METRICS},
        "response_type_accuracy": "response_type",
        "returned_place_ids_unique": "search",
    }
    result = dict(metrics)
    for name in result:
        group = groups.get(name)
        if name.startswith(SEARCH_PREFIXES):
            group = "search"
        if name.startswith("memory_"):
            group = "memory"
        if group is not None and (not live or coverage.get(group) is not True):
            result[name] = None
    return result
