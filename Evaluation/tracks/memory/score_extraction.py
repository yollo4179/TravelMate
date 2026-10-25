"""Preserve the existing explicit/inferred preference observation checks."""
from typing import Any


def score_extraction(case: dict[str, Any], record: dict[str, Any]) -> dict[str, float | None]:
    metrics: dict[str, float | None] = {}
    memory = case["expectations"]["memory"]
    if memory:
        observations = record.get("observations") or {}
        metrics["inferred_memory_requires_confirmation"] = None
        metrics["explicit_preference_extraction_correct"] = None
        if isinstance(record.get("extracted_preferences"), list) and memory.get("explicit_preference"):
            metrics["explicit_preference_extraction_correct"] = float(any(
                fact.get("facet") == memory["explicit_preference"] and fact.get("basis") == "explicit"
                for fact in record["extracted_preferences"] if isinstance(fact, dict)
            ))
        if memory.get("inference_requires_confirmation") and isinstance(observations, dict) and observations.get("source") == "backend_observation" and observations.get("memory_job_completed"):
            metrics["inferred_memory_requires_confirmation"] = float(all(
                event.get("basis") != "inferred" or not event.get("persisted") or event.get("user_confirmed")
                for event in observations.get("memory_events", [])
            ))
    return metrics
