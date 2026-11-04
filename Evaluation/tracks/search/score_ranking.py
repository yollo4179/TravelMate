"""Score an embedding or reranked ordering with the same query-specific gold."""
from typing import Any
from common.metrics.ranking import ranking_metrics


def score_order(returned_ids: list[Any], judgments: dict[Any, int]) -> dict[str, float]:
    return ranking_metrics(returned_ids, judgments)


def score_search_api_record(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    returned_ids = record["ranked_place_ids"]
    judgments = {item["place_id"]: item["relevance"] for item in case["place_judgments"]}
    metrics = score_order(returned_ids, judgments)
    metrics.update({
        "returned_place_ids_unique": float(len(set(returned_ids)) == len(returned_ids)),
        "judged_at_5": sum(place_id in judgments for place_id in returned_ids[:5]),
        "judged_at_10": sum(place_id in judgments for place_id in returned_ids[:10]),
    })
    coverage = {
        "top_1_unjudged": bool(returned_ids) and returned_ids[0] not in judgments,
        "unjudged_place_ids_at_5": [place_id for place_id in returned_ids[:5] if place_id not in judgments],
        "unjudged_place_ids_at_10": [place_id for place_id in returned_ids[:10] if place_id not in judgments],
    }
    return {"metrics": metrics, "judgment_coverage": coverage, "issues": []}
