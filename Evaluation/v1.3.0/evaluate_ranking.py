"""Score reranking and embedding-only orderings against authored place judgments."""

from __future__ import annotations

import json
import math
import csv
import argparse
from collections import Counter
from pathlib import Path
from typing import Any

import build_dataset
from ragas_support.langsmith_observability import evaluation_span


ROOT = Path(__file__).resolve().parent
CUTOFF = 10
RANKING_VERSIONS = ("v1_semantic_only", "v2_reranked")
METRIC_NAMES = (
    "ndcg_at_10",
    "map_at_10",
    "mrr_at_10",
    "recall_at_10",
    "precision_at_10",
    "f1_at_10",
)


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
    relevant_ranks: list[int] = []
    seen_relevant_ids: set[int] = set()
    for rank, place_id in enumerate(top_ids, start=1):
        if place_id in relevant_ids and place_id not in seen_relevant_ids:
            relevant_ranks.append(rank)
            seen_relevant_ids.add(place_id)
    relevant_hits = len(relevant_ranks)
    precision_at_cutoff = relevant_hits / CUTOFF
    recall_at_cutoff = relevant_hits / len(relevant_ids) if relevant_ids else 0.0
    average_precision = (
        sum(
            len({place_id for place_id in top_ids[:rank] if place_id in relevant_ids}) / rank
            for rank in relevant_ranks
        )
        / min(len(relevant_ids), CUTOFF)
        if relevant_ids
        else 0.0
    )
    return {
        "ndcg_at_10": dcg(top_grades) / ideal_dcg if ideal_dcg else 0.0,
        "map_at_10": average_precision,
        "mrr_at_10": reciprocal_rank,
        "recall_at_10": recall_at_cutoff,
        "precision_at_10": precision_at_cutoff,
        "f1_at_10": (
            2 * precision_at_cutoff * recall_at_cutoff / (precision_at_cutoff + recall_at_cutoff)
            if precision_at_cutoff + recall_at_cutoff
            else 0.0
        ),
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
    scores: dict[str, dict[str, float]] = {}
    for version in RANKING_VERSIONS:
        with evaluation_span(
            operation="travelmate.ranking_metrics",
            case_id=case["case_id"],
            strategy_version=version,
            metric_name="ranking_metrics_at_10",
            inputs={
                "query": case["query"],
                "cutoff": CUTOFF,
                "relevance_threshold": 2,
                "judgment_count": len(judgments),
                "retrieved_place_count": len(comparison[version]["place_ids"]),
            },
        ) as ranking_trace:
            scores[version] = score_order(comparison[version]["place_ids"], judgments)
            if ranking_trace is not None:
                for metric_name, metric_score in scores[version].items():
                    ranking_trace.set_attribute(f"evaluation.{metric_name}", metric_score)
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


def evaluate(root: Path = ROOT, env_file: Path | None = None) -> dict[str, Any]:
    from dotenv import load_dotenv

    configured_env_file = env_file or root.resolve().parents[1] / ".env"
    if configured_env_file.is_file():
        load_dotenv(configured_env_file, override=False)

    cases = read_jsonl(root / "development.jsonl")
    review_judgments = read_review_judgments(root / "review_notes_filled_v1.3.0.csv")
    results = []
    skipped_cases = []
    for case in cases:
        if case["answerability"] != "answerable":
            continue
        result = evaluate_case(case, review_judgments)
        if result is None:
            skipped_cases.append(case)
            continue
        results.append(result)
    skipped = Counter(
        case.get("execution", {}).get("condition_coverage", "not_run")
        for case in skipped_cases
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
        "metric_interpretation": "Ranking metrics use authored relevance grades >= 2 as relevant; NDCG uses graded relevance. Precision, recall, F1, MAP, NDCG and MRR are measured at cutoff 10. Scores use explicit judgments only and are candidate-pool indicators, not exhaustive corpus recall.",
    }
    build_dataset.write_jsonl(root / "ranking_results.jsonl", results)
    build_dataset.write_json(root / "ranking_summary.json", summary)
    build_dataset.refresh_runtime_exports(root)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path, help="Defaults to the repository root .env")
    arguments = parser.parse_args()
    print(json.dumps(evaluate(arguments.root, arguments.env_file), ensure_ascii=False, indent=2))
