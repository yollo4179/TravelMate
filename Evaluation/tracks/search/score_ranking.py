"""Score an embedding or reranked ordering with the same query-specific gold."""
from typing import Any
from common.metrics.ranking import ranking_metrics
from common.observability.search_records import search_quality_observed


def score_order(returned_ids: list[Any], judgments: dict[Any, int]) -> dict[str, float]:
    return ranking_metrics(returned_ids, judgments)


def score_search_api_record(case: dict[str, Any], record: dict[str, Any]) -> dict[str, Any]:
    identifiers = record.get("ranked_place_ids") or []
    judgments = {item["place_id"]: item["relevance"] for item in case["place_judgments"]}
    observed = search_quality_observed(record)
    metrics = score_order(identifiers, judgments)
    metrics.update({
        "returned_place_ids_unique": float(len(set(identifiers)) == len(identifiers)),
        "judged_at_5": sum(identifier in judgments for identifier in identifiers[:5]),
        "judged_at_10": sum(identifier in judgments for identifier in identifiers[:10]),
    })
    return {
        "metrics": {name: value if observed else None for name, value in metrics.items()},
        "judgment_coverage": {
            "unjudged_place_ids_at_10": [identifier for identifier in identifiers[:10] if identifier not in judgments],
            "search_quality_observed": observed,
        },
        "issues": [] if observed else ["MOCK, failed, unexecuted, partial, or runtime-unverified search has no quality score"],
    }
