"""Compare frozen holdout orders provisionally without converting unknown labels to zero."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from enum import StrEnum
import math
from pathlib import Path
import random
from statistics import fmean
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.io import digest, read_json, read_jsonl, write_json
from common.metrics.ranking import ranking_metrics
from tracks.search.holdout import RankingMode, check_frozen, read_cases, write_review_csv
from tracks.search.judge_candidates import read_csv

METRICS = ("ndcg_at_10", "top_1_accuracy", "mrr_at_10", "precision_at_5", "recall_at_10")


class Eligibility(StrEnum):
    COMPLETE_POSITIVE = "fully_judged_with_relevant"
    COMPLETE_NO_RELEVANT = "fully_judged_no_relevant_in_pool"
    UNKNOWN = "unknown_labels_present"
    NO_CANDIDATES = "no_candidates"


def classify(grades: list[str]) -> Eligibility:
    if not grades:
        return Eligibility.NO_CANDIDATES
    if "unknown" in grades:
        return Eligibility.UNKNOWN
    if any(int(grade) >= 2 for grade in grades):
        return Eligibility.COMPLETE_POSITIVE
    return Eligibility.COMPLETE_NO_RELEVANT


def cluster_interval(
    family_deltas: list[float],
    repetitions: int = 20000,
    seed: int = 20261028,
) -> list[float] | None:
    if not family_deltas:
        return None
    generator = random.Random(seed)
    count = len(family_deltas)
    samples = sorted(fmean(generator.choices(family_deltas, k=count)) for _ in range(repetitions))
    return [samples[math.floor((repetitions - 1) * fraction)] for fraction in (0.025, 0.975)]


def compare_complete(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if not rows:
        return {"case_count": 0, "family_count": 0, "metrics": {}}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["family_id"]].append(row)
    results = {}
    for metric in METRICS:
        semantic = [fmean(row[RankingMode.SEMANTIC_ONLY][metric] for row in members) for members in grouped.values()]
        reranked = [fmean(row[RankingMode.RERANKED][metric] for row in members) for members in grouped.values()]
        deltas = [after - before for before, after in zip(semantic, reranked, strict=True)]
        case_deltas = [row[RankingMode.RERANKED][metric] - row[RankingMode.SEMANTIC_ONLY][metric] for row in rows]
        results[metric] = {
            "semantic_family_weighted_mean": fmean(semantic),
            "reranked_family_weighted_mean": fmean(reranked), "paired_delta": fmean(deltas),
            "paired_family_bootstrap_95_interval": cluster_interval(deltas),
            "case_win_tie_loss": dict(Counter("win" if value > 1e-12 else "loss" if value < -1e-12 else "tie" for value in case_deltas)),
            "semantic_case_weighted_mean": fmean(row[RankingMode.SEMANTIC_ONLY][metric] for row in rows),
            "reranked_case_weighted_mean": fmean(row[RankingMode.RERANKED][metric] for row in rows),
        }
    return {"case_count": len(rows), "family_count": len(grouped), "case_ids": [row["case_id"] for row in rows], "metrics": results}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    check_frozen(arguments.dataset)
    label_path = arguments.run_root / "blind-review-20261027/candidates.csv"
    inputs = read_json(arguments.output / "scoring_inputs.json")
    if inputs["sha256"].get(label_path.as_posix(), inputs["sha256"].get(str(label_path))) != digest(label_path):
        # The freeze record can contain workspace-relative paths on Windows.
        matching = [value for path, value in inputs["sha256"].items() if path.replace("\\", "/").endswith("blind-review-20261027/candidates.csv")]
        if matching != [digest(label_path)]:
            raise ValueError("The labels changed after the pre-unblinding freeze")
    _, labels = read_csv(label_path)
    if not all(row["rubric_review_status"] == "completed" for row in labels):
        raise ValueError("Finish all rubric checks before unblinding")
    mappings = read_jsonl(arguments.run_root / "blind-review-20261027/private_mapping.jsonl")
    mapped = {item["candidate_key"]: item for item in mappings}
    if len(mapped) != len(labels) or set(mapped) != {row["candidate_key"] for row in labels}:
        raise ValueError("The blinded mapping must match every label exactly once")
    grouped = defaultdict(list)
    for label in labels:
        assert mapped[label["candidate_key"]]["case_id"] == label["case_id"]
        grouped[label["case_id"]].append(label)
    records = {
        mode: {record["case_id"]: record for record in read_jsonl(arguments.run_root / f"collection-20261027/{filename}_records.jsonl")}
        for mode, filename in ((RankingMode.SEMANTIC_ONLY, "embedding"), (RankingMode.RERANKED, "reranked"))
    }
    scored = []
    coverage = []
    priority = []
    primary_status = Counter()
    for case in read_cases(arguments.dataset):
        selected = grouped[case["case_id"]]
        grades = {mapped[row["candidate_key"]]["place_id"]: row["relevance"] for row in selected}
        eligibility = classify(list(grades.values()))
        if case["stratum"] == "primary":
            primary_status[eligibility] += 1
        coverage.append({
            "case_id": case["case_id"], "query": case["input"]["query"], "stratum": case["stratum"],
            "family_id": case["family_id"], "query_type": case["query_type"],
            "eligibility": eligibility, "candidate_count": len(selected),
            "unknown_count": sum(grade == "unknown" for grade in grades.values()),
            "known_relevant_count": sum(grade in ("2", "3") for grade in grades.values()),
        })
        orders = {}
        for mode in RankingMode:
            record = records[mode][case["case_id"]]
            assert record["http_status"] == 200 and record["input_sha256"] == case["input_sha256"]
            orders[mode] = record["ranked_place_ids"][:10]
            assert len(orders[mode]) == len(set(orders[mode]))
            assert all(place_id in grades for place_id in orders[mode]), "Unjudged top-10 result"
        assert set(grades) == set(orders[RankingMode.SEMANTIC_ONLY]) | set(orders[RankingMode.RERANKED])
        coverage[-1].update({f"{mode}_returned_count": len(orders[mode]) for mode in RankingMode})
        if case["stratum"] != "primary":
            continue
        if eligibility == Eligibility.UNKNOWN:
            for row in selected:
                if row["relevance"] == "unknown":
                    priority.append({
                        "case_id": case["case_id"], "family_id": case["family_id"] ,
                        "unknowns_to_resolve_in_question": coverage[-1]["unknown_count"],
                        "candidate_key": row["candidate_key"], "query": row["query"], "place_name": row["place_name"],
                        "missing_evidence": row["rationale"], "source_homepage_url": row["source_homepage_url"],
                    })
        if eligibility != Eligibility.COMPLETE_POSITIVE:
            continue
        judgments = {identifier: int(grade) for identifier, grade in grades.items()}
        scored.append({
            "case_id": case["case_id"], "family_id": case["family_id"],
            **{mode: ranking_metrics(order, judgments) for mode, order in orders.items()},
        })
    comparison = compare_complete(scored)
    report = {
        "status": "provisional_ai_labels_only", "dataset": arguments.dataset.name,
        "label_source": "ai_judgment_with_codex_rubric_recheck", "human_confirmed_primary_cases": 0,
        "protocol_primary_result_available": False, "primary_eligibility": dict(primary_status),
        "provisional_primary_comparison": comparison,
        "challenge_case_count": sum(row["stratum"] == "challenge" for row in coverage),
        "unknown_label_count_all_cases": sum(row["relevance"] == "unknown" for row in labels),
        "primary_unknown_label_count": len(priority),
        "aggregation": "Equal query-family weight; bootstrap of paired family means, 20000 samples, seed 20261028",
        "limitations": [
            "The frozen primary endpoint requires human-confirmed labels; this is a separate provisional AI-label analysis.",
            "Unknown labels are never scored as zero. Any unknown in the pooled union excludes that query from complete-case ranking means.",
            "The eligible subset is selected by evidence completeness, is very small, and does not represent all 60 primary questions.",
            "Recall is only against known relevant places in the top-10 union, not the whole corpus.",
            "Each mode retrieved independently; this compares complete search pipelines, not reranking a proven identical candidate list.",
            "Latency collection includes cold calls and is not a controlled latency benchmark.",
            "New queries share the existing Seoul corpus; results do not establish generalization to unseen domains or corpora.",
        ],
        "candidates_sha256": digest(label_path),
        "rankings_sha256": {mode: digest(arguments.run_root / f"collection-20261027/{filename}_records.jsonl") for mode, filename in ((RankingMode.SEMANTIC_ONLY, "embedding"), (RankingMode.RERANKED, "reranked"))},
    }
    write_json(arguments.output / "comparison.json", report)
    write_review_csv(arguments.output / "coverage.csv", coverage, list(coverage[0]))
    priority.sort(key=lambda row: (int(row["unknowns_to_resolve_in_question"]), row["family_id"], row["case_id"], row["candidate_key"]))
    write_review_csv(arguments.output / "evidence_priority.csv", priority, list(priority[0]))
    write_json(arguments.output / "per_case_metrics.json", scored)
    print(report)


if __name__ == "__main__":
    main()
