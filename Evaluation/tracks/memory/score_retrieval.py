"""Recall uses scenario-specific memory IDs, never tourism place judgments."""
from typing import Any
from common.metrics.ranking import ranking_metrics


def score_retrieval(case: dict[str, Any], record: dict[str, Any]) -> dict[str, float]:
    metrics: dict[str, float] = {}
    memory = case["expectations"]["memory"]
    if memory and memory.get("relevant_memory_ids") and isinstance(record.get("memory_retrieval_ids"), list):
        metrics.update(ranking_metrics(record["memory_retrieval_ids"], {identifier: 3 for identifier in memory["relevant_memory_ids"]}, "memory_"))
    return metrics
