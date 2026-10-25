"""Score an embedding or reranked ordering with the same query-specific gold."""
from typing import Any
from common.metrics.ranking import ranking_metrics


def score_order(returned_ids: list[Any], judgments: dict[Any, int]) -> dict[str, float]:
    return ranking_metrics(returned_ids, judgments)
