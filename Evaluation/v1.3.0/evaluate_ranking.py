"""Score reranking and embedding-only orderings against authored place judgments."""

from __future__ import annotations

import json
import math
import csv
from collections import Counter
from pathlib import Path
from typing import Any

import build_dataset


ROOT = Path(__file__).resolve().parent
CUTOFF = 10
RANKING_VERSIONS = ("v1_semantic_only", "v2_reranked")
METRIC_NAMES = ("ndcg_at_10", "mrr_at_10", "recall_at_10", "precision_at_10")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def read_review_judgments(path: Path) -> dict[str, dict[int, int]]:
    with path.open(encoding="utf-8-sig", newline="") as review_file:
        rows = csv.DictReader(review_file)
        return {
            case_id: {
                int(row["place_id"]): int(row["relevance"])
                for row in case_rows
                if row["place_id"] and row["relevance"]
            }
            for case_id, case_rows in group_review_rows(rows).items()
        }


def group_review_rows(rows: Any) -> dict[str, list[dict[str, str]]]:
    grouped_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        grouped_rows.setdefault(row["case_id"], []).append(row)
    return grouped_rows


def dcg(relevances: list[int]) -> float:
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(relevances[:CUTOFF], start=1)
    )


def score_order(place_ids: list[int], judgments: dict[int, int]) -> dict[str, float]:
    relevant_ids = {place_id for place_id, grade in judgments.items() if grade >= 2}
    top_ids = place_ids[:CUTOFF]
    top_grades = [judgments.get(place_id, 0) for place_id in top_ids]
    ideal_grades = sorted(judgments.values(), reverse=True)
    ideal_dcg = dcg(ideal_grades)
    reciprocal_rank = next(
        (1 / rank for rank, place_id in enumerate(top_ids, start=1) if place_id in relevant_ids),
        0.0,
    )
    relevant_hits = sum(place_id in relevant_ids for place_id in top_ids)
    return {
        "ndcg_at_10": dcg(top_grades) / ideal_dcg if ideal_dcg else 0.0,
        "mrr_at_10": reciprocal_rank,
        "recall_at_10": relevant_hits / len(relevant_ids) if relevant_ids else 0.0,
        "precision_at_10": relevant_hits / CUTOFF,
    }


def evaluate_case(
    case: dict[str, Any],
    review_judgments: dict[str, dict[int, int]],
) -> dict[str, Any] | None:
    if case["answerability"] != "answerable":
        return None
    execution = case.get("execution", {})
    if execution.get("status") != "completed" or execution.get("condition_coverage") != "complete":
        return None
    comparison = case.get("ranking_comparison", {})
    if set(comparison) != set(RANKING_VERSIONS):
        return None
    if any(comparison[version].get("execution", {}).get("status") != "completed" for version in RANKING_VERSIONS):
        return None
    judgments = review_judgments.get(case["case_id"], {})
    if not judgments:
        return None
    scores = {
        version: score_order(comparison[version]["place_ids"], judgments)
        for version in RANKING_VERSIONS
    }
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "evaluation_track": case["evaluation_track"],
        "judgment_count": len(judgments),
        "relevant_judgment_count": sum(grade >= 2 for grade in judgments.values()),
        "ranking_versions": scores,
        "delta_v2_minus_v1": {
            metric: scores["v2_reranked"][metric] - scores["v1_semantic_only"][metric]
            for metric in METRIC_NAMES
        },
    }


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {version: {metric: None for metric in METRIC_NAMES} for version in RANKING_VERSIONS}
    return {
        version: {
            metric: sum(result["ranking_versions"][version][metric] for result in results) / len(results)
            for metric in METRIC_NAMES
        }
        for version in RANKING_VERSIONS
    }


def evaluate(root: Path = ROOT) -> dict[str, Any]:
    cases = read_jsonl(root / "development.jsonl")
    review_judgments = read_review_judgments(root / "review_notes_filled_v1.3.0.csv")
    results = [
        result
        for case in cases
        if (result := evaluate_case(case, review_judgments)) is not None
    ]
    skipped = Counter(
        case.get("execution", {}).get("condition_coverage", "not_run")
        for case in cases
        if case["answerability"] == "answerable" and evaluate_case(case, review_judgments) is None
    )
    averages = aggregate(results)
    summary = {
        "status": "completed" if results else "not_run",
        "split": "development",
        "dataset_version": "1.3.0",
        "cutoff": CUTOFF,
        "case_count": len(results),
        "skipped_answerable_case_count": sum(skipped.values()),
        "skipped_by_condition_coverage": dict(skipped),
        "ranking_versions": {
            "v1_semantic_only": {"description": "Embedding similarity order, before reranking", **averages["v1_semantic_only"]},
            "v2_reranked": {"description": "BGE reranker order over the same embedding top-30 candidate pool", **averages["v2_reranked"]},
        },
        "delta_v2_minus_v1": {
            metric: averages["v2_reranked"][metric] - averages["v1_semantic_only"][metric]
            if results else None
            for metric in METRIC_NAMES
        },
        "judgment_scope": "partial_explicit_judgments; unjudged places are not asserted irrelevant",
        "judgment_source": "review_notes_filled_v1.3.0.csv",
        "metric_interpretation": "Ranking metrics use only authored place relevance judgments. Scores are candidate-pool indicators, not exhaustive corpus recall.",
    }
    build_dataset.write_jsonl(root / "ranking_results.jsonl", results)
    build_dataset.write_json(root / "ranking_summary.json", summary)
    build_dataset.refresh_runtime_exports(root)
    return summary


if __name__ == "__main__":
    print(json.dumps(evaluate(), ensure_ascii=False, indent=2))
