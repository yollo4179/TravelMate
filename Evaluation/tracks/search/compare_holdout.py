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
from common.observability.search_records import search_quality_observed, search_record_error
from common.paths import EVALUATION_ROOT
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


def compare_observations(
    cases: list[dict[str, Any]],
    labels: list[dict[str, str]],
    mappings: list[dict[str, Any]],
    records: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    mapped = {row["candidate_key"]: row for row in mappings}
    if len(mapped) != len(mappings) or len({row["candidate_key"] for row in labels}) != len(labels):
        raise ValueError("Labels and mappings must have unique candidate keys")
    if set(mapped) != {row["candidate_key"] for row in labels}:
        raise ValueError("Every label requires exactly one preserved blinded mapping")
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for label in labels:
        if mapped[label["candidate_key"]]["case_id"] != label["case_id"]:
            raise ValueError("A label cannot borrow another case's mapping")
        grouped[label["case_id"]].append(label)
    case_ids = {case["case_id"] for case in cases}
    if len(case_ids) != len(cases) or set(grouped) != case_ids:
        raise ValueError("Selected cases and complete label groups must match explicitly")
    indexed: dict[str, dict[str, dict[str, Any]]] = {}
    for mode in RankingMode:
        rows = records[mode.value]
        indexed[mode.value] = {row["case_id"]: row for row in rows}
        if len(indexed[mode.value]) != len(rows) or set(indexed[mode.value]) != case_ids:
            raise ValueError("Each selected case requires its original observation for both modes")
        if any(row.get("ranking_mode") != mode.value for row in rows):
            raise ValueError("The original ranking mode does not match its explicitly bound input file")
    scored: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for case in cases:
        selected = grouped[case["case_id"]]
        record_pair = [indexed[mode.value][case["case_id"]] for mode in RankingMode]
        observation_errors = [search_record_error(case, record) for record in record_pair]
        hashes_match = all(record.get("input_sha256") == case["input_sha256"] for record in record_pair)
        observed = hashes_match and not any(observation_errors) and all(search_quality_observed(record) for record in record_pair)
        labels_mock = any(row.get("label_source") == "mock_judgment" or row.get("review_status") == "mock_regression_only" for row in selected)
        grades = [row["relevance"] for row in selected]
        if any(grade not in {"0", "1", "2", "3", "unknown"} for grade in grades):
            raise ValueError("Incomplete labels remain unscored; do not turn blanks into zero")
        eligibility = classify(grades)
        coverage.append({"case_id": case["case_id"], "stratum": case["stratum"], "family_id": case["family_id"], "label_eligibility": eligibility.value, "search_quality_observed": observed, "mock_labels": labels_mock, "observation_errors": observation_errors, "input_hashes_match": hashes_match})
        if not observed or labels_mock:
            continue
        judgments = {mapped[row["candidate_key"]]["place_id"]: int(row["relevance"]) for row in selected if row["relevance"] != "unknown"}
        orders = {mode.value: indexed[mode.value][case["case_id"]]["ranked_place_ids"][:10] for mode in RankingMode}
        pooled = set(orders[RankingMode.SEMANTIC_ONLY.value]) | set(orders[RankingMode.RERANKED.value])
        label_ids = {mapped[row["candidate_key"]]["place_id"] for row in selected}
        if len(label_ids) != len(selected) or label_ids != pooled:
            raise ValueError("Every pooled top-10 place requires exactly one label")
        if case["stratum"] != "primary" or eligibility != Eligibility.COMPLETE_POSITIVE:
            continue
        scored.append({"case_id": case["case_id"], "family_id": case["family_id"], **{mode: ranking_metrics(order, judgments) for mode, order in orders.items()}})
    return {
        "status": "provisional_labels_only" if scored else "not_evaluated",
        "protocol_primary_result_available": False,
        "label_policy": "Human confirmation is not inferred from AI labels or quote validation",
        "provisional_primary_comparison": compare_complete(scored),
        "coverage": coverage,
        "per_case_metrics": scored,
        "limitations": ["MOCK, failed, unexecuted, incompatible and runtime-unverified observations have no ranking quality score.", "Unknown labels are never zero; one unknown excludes the whole pooled case from complete-case means.", "Each mode retrieves independently; this is not proof of identical candidates.", "This provisional comparison does not certify plan rules, routes, explanation quality or the frozen human-label endpoint."],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--embedding-records", type=Path, required=True)
    parser.add_argument("--reranking-records", type=Path, required=True)
    parser.add_argument("--scoring-inputs", type=Path, required=True)
    parser.add_argument("--case-id", action="append", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    check_frozen(arguments.dataset)
    if arguments.output_dir.exists() or arguments.output_dir.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
        raise FileExistsError("Comparison needs a new output directory outside frozen datasets")
    paths = {"labels": arguments.labels, "mapping": arguments.mapping, "embedding_records": arguments.embedding_records, "reranking_records": arguments.reranking_records}
    hashes = {name: digest(path) for name, path in paths.items()}
    if read_json(arguments.scoring_inputs).get("sha256") != hashes:
        raise ValueError("Explicit pre-unblinding input hashes must match all four files exactly")
    selected = set(arguments.case_id)
    all_cases = {case["case_id"]: case for case in read_cases(arguments.dataset)}
    if len(selected) != len(arguments.case_id) or not selected <= all_cases.keys():
        raise ValueError("Select unique existing case IDs explicitly")
    _, labels = read_csv(arguments.labels)
    mappings = read_jsonl(arguments.mapping)
    records = {mode: [row for row in read_jsonl(paths[name]) if row["case_id"] in selected] for mode, name in ((RankingMode.SEMANTIC_ONLY.value, "embedding_records"), (RankingMode.RERANKED.value, "reranking_records"))}
    report = compare_observations([all_cases[identifier] for identifier in arguments.case_id], [row for row in labels if row["case_id"] in selected], [row for row in mappings if row["case_id"] in selected], records)
    report.update(dataset=arguments.dataset.name, dataset_manifest_sha256=digest(arguments.dataset / "manifest.json"), input_sha256=hashes, selected_case_ids=arguments.case_id)
    write_json(arguments.output_dir / "comparison.json", report)


if __name__ == "__main__":
    main()
