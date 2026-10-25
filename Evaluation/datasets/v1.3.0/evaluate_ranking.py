"""Score reranking and embedding-only orderings against authored place judgments."""

from __future__ import annotations

import json
import math
import csv
import argparse
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import build_dataset
from ragas_support.langsmith_observability import evaluation_span


ROOT = Path(__file__).resolve().parent
CUTOFFS = (5, 10)
RANKING_VERSIONS = ("v1_semantic_only", "v2_reranked")
METRIC_BASE_NAMES = ("ndcg", "map", "mrr", "recall", "precision", "f1")


def metric_names(cutoff: int) -> tuple[str, ...]:
    return tuple(dict.fromkeys((
        *(f"{metric}_at_{cutoff}" for metric in METRIC_BASE_NAMES),
        "top_1_accuracy",
        f"top_{cutoff}_accuracy",
    )))


def validate_cutoff(cutoff: int) -> None:
    if type(cutoff) is not int or cutoff <= 0:
        raise ValueError("cutoff must be a positive integer")


def log_progress(root: Path, cutoff: int, message: str) -> None:
    output_dir = root / f"ranking_at_{cutoff}"
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / "run.log"
    timestamp = datetime.now(timezone.utc).isoformat()
    with log_path.open("a", encoding="utf-8", newline="\n") as log_file:
        log_file.write(f"{timestamp} {message}\n")
    print(message, flush=True)


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


def dcg(relevances: list[int], cutoff: int) -> float:
    return sum(
        (2**grade - 1) / math.log2(rank + 1)
        for rank, grade in enumerate(relevances[:cutoff], start=1)
    )


def score_order(place_ids: list[int], judgments: dict[int, int], cutoff: int = 10) -> dict[str, float]:
    validate_cutoff(cutoff)
    relevant_ids = {place_id for place_id, grade in judgments.items() if grade >= 2}
    top_ids = place_ids[:cutoff]
    top_grades = [judgments.get(place_id, 0) for place_id in top_ids]
    ideal_grades = sorted(judgments.values(), reverse=True)
    ideal_dcg = dcg(ideal_grades, cutoff)
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
    precision_at_cutoff = relevant_hits / cutoff
    recall_at_cutoff = relevant_hits / len(relevant_ids) if relevant_ids else 0.0
    average_precision = (
        sum(
            len({place_id for place_id in top_ids[:rank] if place_id in relevant_ids}) / rank
            for rank in relevant_ranks
        )
        / min(len(relevant_ids), cutoff)
        if relevant_ids
        else 0.0
    )
    return dict(zip(metric_names(cutoff), (
        dcg(top_grades, cutoff) / ideal_dcg if ideal_dcg else 0.0,
        average_precision,
        reciprocal_rank,
        recall_at_cutoff,
        precision_at_cutoff,
        (
            2 * precision_at_cutoff * recall_at_cutoff / (precision_at_cutoff + recall_at_cutoff)
            if precision_at_cutoff + recall_at_cutoff
            else 0.0
        ),
        float(bool(top_ids) and top_ids[0] in relevant_ids),
        float(relevant_hits > 0),
    )))


def judgment_coverage(
    place_ids: list[int],
    judgments: dict[int, int],
    cutoff: int,
) -> dict[str, Any]:
    top_ids = place_ids[:cutoff]
    unjudged_ids = [place_id for place_id in top_ids if place_id not in judgments]
    relevant_ids = {place_id for place_id, grade in judgments.items() if grade >= 2}
    return {
        "returned_at_k": len(top_ids),
        "judged_at_k": len(top_ids) - len(unjudged_ids),
        "unjudged_place_ids_at_k": unjudged_ids,
        "top_1_unjudged": bool(top_ids) and top_ids[0] not in judgments,
        "top_k_no_known_hit_with_unjudged_candidates": bool(unjudged_ids) and not relevant_ids.intersection(top_ids),
    }


def evaluate_case(
    case: dict[str, Any],
    review_judgments: dict[str, dict[int, int]],
    cutoff: int,
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
            metric_name=f"ranking_metrics_at_{cutoff}",
            project_name=f"travelmate-ragas-v1.3.0-at-{cutoff}",
            inputs={
                "query": case["query"],
                "cutoff": cutoff,
                "relevance_threshold": 2,
                "judgment_count": len(judgments),
                "retrieved_place_count": len(comparison[version]["place_ids"]),
            },
        ) as ranking_trace:
            scores[version] = score_order(comparison[version]["place_ids"], judgments, cutoff)
            if ranking_trace is not None:
                for metric_name, metric_score in scores[version].items():
                    ranking_trace.set_attribute(f"evaluation.{metric_name}", metric_score)
    return {
        "case_id": case["case_id"],
        "query": case["query"],
        "evaluation_track": case["evaluation_track"],
        "cutoff": cutoff,
        "judgment_count": len(judgments),
        "relevant_judgment_count": sum(grade >= 2 for grade in judgments.values()),
        "judgment_coverage": {
            version: judgment_coverage(comparison[version]["place_ids"], judgments, cutoff)
            for version in RANKING_VERSIONS
        },
        "ranking_versions": scores,
        "delta_v2_minus_v1": {
            metric: scores["v2_reranked"][metric] - scores["v1_semantic_only"][metric]
            for metric in metric_names(cutoff)
        },
    }


def aggregate(results: list[dict[str, Any]], cutoff: int) -> dict[str, Any]:
    names = metric_names(cutoff)
    if not results:
        return {version: {metric: None for metric in names} for version in RANKING_VERSIONS}
    return {
        version: {
            metric: sum(result["ranking_versions"][version][metric] for result in results) / len(results)
            for metric in names
        }
        for version in RANKING_VERSIONS
    }


def evaluate(
    root: Path = ROOT,
    env_file: Path | None = None,
    *,
    cutoffs: tuple[int, ...] = CUTOFFS,
) -> dict[str, Any]:
    from dotenv import load_dotenv

    if not cutoffs or len(set(cutoffs)) != len(cutoffs):
        raise ValueError("cutoffs must be nonempty and unique")
    for cutoff in cutoffs:
        validate_cutoff(cutoff)
    configured_env_file = env_file or root.resolve().parents[1] / ".env"
    if configured_env_file.is_file():
        load_dotenv(configured_env_file, override=False)

    cases = read_jsonl(root / "development.jsonl")
    review_judgments = read_review_judgments(root / "review_notes_filled_v1.3.0.csv")
    cutoff_summaries: dict[str, dict[str, Any]] = {}
    results_by_cutoff: dict[int, list[dict[str, Any]]] = {}
    for cutoff in cutoffs:
        output_dir = root / f"ranking_at_{cutoff}"
        output_dir.mkdir(parents=True, exist_ok=True)
        (output_dir / "run.log").write_text("", encoding="utf-8")
        log_progress(root, cutoff, f"ranking @{cutoff}: 채점 시작")
        results: list[dict[str, Any]] = []
        skipped_cases: list[dict[str, Any]] = []
        eligible_cases = [case for case in cases if case["answerability"] == "answerable"]
        for case in eligible_cases:
            result = evaluate_case(case, review_judgments, cutoff)
            if result is None:
                skipped_cases.append(case)
                continue
            results.append(result)
            log_progress(root, cutoff, f"ranking @{cutoff}: {case['case_id']} 완료 ({len(results)}/{len(eligible_cases)})")
        skipped = Counter(
            case.get("execution", {}).get("condition_coverage", "not_run")
            for case in skipped_cases
        )
        averages = aggregate(results, cutoff)
        names = metric_names(cutoff)
        evaluated_case_ids = {result["case_id"] for result in results}
        summary = {
            "status": "completed" if results else "not_run",
            "split": "development",
            "dataset_version": "1.3.0",
            "cutoff": cutoff,
            "case_count": len(results),
            "evaluated_case_ids": [result["case_id"] for result in results],
            "skipped_answerable_case_count": sum(skipped.values()),
            "skipped_by_condition_coverage": dict(skipped),
            "ranking_versions": {
                "v1_semantic_only": {"description": "Embedding similarity order, before reranking", **averages["v1_semantic_only"]},
                "v2_reranked": {"description": "BGE reranker order over the same embedding top-30 candidate pool", **averages["v2_reranked"]},
            },
            "delta_v2_minus_v1": {
                metric: averages["v2_reranked"][metric] - averages["v1_semantic_only"][metric]
                if results else None
                for metric in names
            },
            "judgment_scope": "partial_explicit_judgments; unjudged places are not asserted irrelevant",
            "judgment_source": "review_notes_filled_v1.3.0.csv",
            "accuracy_definitions": {
                "top_1_accuracy": "Fraction of evaluated queries whose first result has human relevance >= 2.",
                f"top_{cutoff}_accuracy": f"Fraction of evaluated queries with at least one human relevance >= 2 result in the first {cutoff} positions (Hit@{cutoff}).",
                f"recall_at_{cutoff}": "Mean per-query fraction of the known relevant place IDs retrieved in the first K positions; distinct from Top-K accuracy.",
            },
            "judgment_coverage": {
                version: {
                    "top_1_unjudged_case_count": sum(result["judgment_coverage"][version]["top_1_unjudged"] for result in results),
                    "top_k_no_known_hit_with_unjudged_case_count": sum(result["judgment_coverage"][version]["top_k_no_known_hit_with_unjudged_candidates"] for result in results),
                    "judged_result_count_at_k": sum(result["judgment_coverage"][version]["judged_at_k"] for result in results),
                    "returned_result_count_at_k": sum(result["judgment_coverage"][version]["returned_at_k"] for result in results),
                }
                for version in RANKING_VERSIONS
            },
            "input_sha256": {
                name: build_dataset.digest_file(root / name)
                for name in ("development.jsonl", "review_notes_filled_v1.3.0.csv")
            },
            "review_statuses": sorted({
                case["review"]["status"] for case in cases
                if case["case_id"] in evaluated_case_ids
            }),
            "metric_interpretation": f"Human relevance >= 2 defines a known relevant place. Top-1 accuracy and Top-{cutoff} accuracy are query-level hit rates, not precision or recall. Ranking metrics use cutoff {cutoff}; NDCG uses graded relevance. Unjudged candidates are not confirmed errors: no-known-hit scores are conservative when candidates remain unjudged. Recall covers the known relevant set, not exhaustive corpus recall.",
            "langsmith_project": f"travelmate-ragas-v1.3.0-at-{cutoff}",
        }
        output_dir = root / f"ranking_at_{cutoff}"
        output_dir.mkdir(parents=True, exist_ok=True)
        build_dataset.write_jsonl(output_dir / "results.jsonl", results)
        build_dataset.write_json(output_dir / "summary.json", summary)
        cutoff_summaries[str(cutoff)] = summary
        results_by_cutoff[cutoff] = results
        log_progress(root, cutoff, f"ranking @{cutoff}: 저장 완료 → {output_dir}")

    primary_cutoff = 10 if 10 in cutoffs else cutoffs[0]
    results = results_by_cutoff[primary_cutoff]
    summary = dict(cutoff_summaries[str(primary_cutoff)])
    summary["cutoffs"] = cutoff_summaries
    build_dataset.write_jsonl(root / "ranking_results.jsonl", results)
    build_dataset.write_json(root / "ranking_summary.json", summary)
    build_dataset.refresh_runtime_exports(root)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--env-file", type=Path, help="Defaults to the repository root .env")
    parser.add_argument("--cutoffs", type=int, nargs="+", default=list(CUTOFFS), help="Top-K and Recall cutoffs; defaults to the existing K=5 and K=10")
    arguments = parser.parse_args()
    print(json.dumps(evaluate(arguments.root, arguments.env_file, cutoffs=tuple(arguments.cutoffs)), ensure_ascii=False, indent=2))
