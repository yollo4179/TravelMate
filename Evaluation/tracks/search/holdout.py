"""Freeze new search questions and prepare human review without inventing gold labels."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from enum import StrEnum
import json
from pathlib import Path
import random
import sys
from typing import Any
import unicodedata

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import canonical_digest, digest, read_json, read_jsonl, write_json, write_jsonl
from common.paths import EVALUATION_ROOT
from common.observability.search_records import search_quality_observed, search_record_error

DEFAULT_HOLDOUT = EVALUATION_ROOT / "datasets/search-holdout-v1.0.0"
REVIEW_SEED = 20261027


class Stratum(StrEnum):
    PRIMARY = "primary"
    CHALLENGE = "challenge"


class QueryType(StrEnum):
    ENTITY = "entity"
    SEMANTIC = "semantic"
    MULTI_CONSTRAINT = "multi_constraint"
    NEGATION = "negation"
    NOISY_INPUT = "noisy_input"
    MULTILINGUAL = "multilingual"
    EVIDENCE_SENSITIVE = "evidence_sensitive"
    OUT_OF_SCOPE = "out_of_scope"


class RankingMode(StrEnum):
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    RERANKED = "RERANKED"


class ReviewStatus(StrEnum):
    PENDING = "pending"


def normalize_query(query: str) -> str:
    return "".join(character.casefold() for character in unicodedata.normalize("NFKC", query) if character.isalnum())


def read_cases(root: Path) -> list[dict[str, Any]]:
    with (root / "source/questions.csv").open(encoding="utf-8-sig", newline="") as source:
        questions = list(csv.DictReader(source))
    families = read_json(root / "source/families.json")
    family_members = [identifier for members in families.values() for identifier in members]
    identifiers = [question["case_id"] for question in questions]
    if len(set(identifiers)) != len(identifiers) or Counter(family_members) != Counter(identifiers):
        raise ValueError("Every unique question must belong to exactly one query family")
    family_by_case = {identifier: family for family, members in families.items() for identifier in members}
    cases = []
    for question in questions:
        Stratum(question["stratum"])
        QueryType(question["query_type"])
        if not question["query"].strip():
            raise ValueError("Questions cannot be blank")
        request = {
            "query": question["query"],
            "conditions": {
                "region": question["region"] or None,
                "city": question["city"] or None,
                "category": question["category"] or None,
            },
        }
        cases.append({
            "case_id": question["case_id"],
            "stratum": question["stratum"],
            "query_type": question["query_type"],
            "family_id": family_by_case[question["case_id"]],
            "input": request,
            "input_sha256": canonical_digest(request),
        })
    return cases


def historical_files(root: Path) -> list[Path]:
    return sorted({
        *root.parent.glob("v*/generated/golden.jsonl"),
        *root.parent.glob("v*/golden.jsonl"),
        *root.parent.glob("v*/source/source_goldenset*.jsonl"),
    })


def character_trigrams(query: str) -> set[str]:
    normalized = normalize_query(query)
    return {normalized[index:index + 3] for index in range(max(1, len(normalized) - 2))}


def overlap_report(
    cases: list[dict[str, Any]],
    paths: list[Path],
) -> dict[str, Any]:
    historical_queries = {
        query
        for path in paths
        for record in read_jsonl(path)
        if (query := record.get("input", {}).get("query") or record.get("query"))
    }
    normalized_history = {normalize_query(query) for query in historical_queries}
    normalized_new = [normalize_query(case["input"]["query"]) for case in cases]
    if len(set(normalized_new)) != len(normalized_new):
        raise ValueError("New questions contain normalized duplicates")
    exact_matches = [case["case_id"] for case in cases if normalize_query(case["input"]["query"]) in normalized_history]
    grams_by_query = {query: character_trigrams(query) for query in sorted(historical_queries)}
    inverted: dict[str, set[str]] = defaultdict(set)
    for query, grams in grams_by_query.items():
        for gram in grams:
            inverted[gram].add(query)
    near_matches = []
    for case in cases:
        grams = character_trigrams(case["input"]["query"])
        candidates = sorted(set().union(*(inverted[gram] for gram in grams)))
        scored = [(len(grams & grams_by_query[query]) / len(grams | grams_by_query[query]), query) for query in candidates]
        nearest = max(scored, default=(0.0, ""))
        near_matches.append({"case_id": case["case_id"], "similarity": nearest[0], "nearest_old_query": nearest[1]})
    return {
        "method": "NFKC/case/punctuation normalized exact check and character-trigram Jaccard nearest neighbor; not a semantic independence proof",
        "historical_unique_query_count": len(historical_queries),
        "exact_match_case_ids": exact_matches,
        "manual_review_threshold": 0.35,
        "near_match_review_required": [row for row in near_matches if row["similarity"] >= 0.35],
        "nearest_historical_queries": near_matches,
    }


def dataset_report(root: Path) -> dict[str, Any]:
    protocol = read_json(root / "protocol.json")
    cases = read_cases(root)
    counts = dict(Counter(case["stratum"] for case in cases))
    if counts != protocol["case_counts"]:
        raise ValueError("Question counts differ from the preregistered protocol")
    if set(case["query_type"] for case in cases) != set(protocol["query_types"]):
        raise ValueError("Question types differ from the preregistered protocol")
    corpus = read_json(root / protocol["corpus_path"])
    supported_cities = {place["city"] for place in corpus}
    for case in cases:
        conditions = case["input"]["conditions"]
        if case["stratum"] == Stratum.PRIMARY and (
            conditions["region"] != "서울" or conditions["city"] is not None and conditions["city"] not in supported_cities
        ):
            raise ValueError("Primary questions must use supported Seoul filters")
    history = historical_files(root)
    if not history:
        raise ValueError("No historical questions available for overlap checking")
    overlap = overlap_report(cases, history)
    if overlap["exact_match_case_ids"]:
        raise ValueError(f"Questions duplicate historical queries: {overlap['exact_match_case_ids']}")
    tracked = [
        root / "source/questions.csv", root / "source/families.json", root / "protocol.json", root / "rubric.md",
        root / protocol["corpus_path"], root / protocol["corpus_snapshot_path"], *history,
    ]
    tracked.extend(path for path in (
        root / "source/question_review.csv",
        root / "source/original_question_review.csv",
        root / "source/review_changes.json",
    ) if path.exists())
    return {
        "dataset_id": protocol["dataset_id"],
        "status": protocol["lifecycle"],
        "human_judgments_complete": False,
        "case_count": len(cases),
        "counts_by_stratum": counts,
        "counts_by_query_type": dict(Counter(case["query_type"] for case in cases)),
        "primary_family_count": len({case["family_id"] for case in cases if case["stratum"] == Stratum.PRIMARY}),
        "files": {path.resolve().relative_to(EVALUATION_ROOT.resolve()).as_posix(): digest(path) for path in tracked},
        "overlap": overlap,
    }


def check_frozen(root: Path) -> dict[str, Any]:
    current = dataset_report(root)
    if current != read_json(root / "manifest.json"):
        raise ValueError("Frozen questions, protocol, corpus or historical inputs changed; create a new version")
    return current


def new_output_directory(output: Path) -> None:
    if output.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
        raise ValueError("Review and response artifacts must stay outside frozen datasets")
    output.mkdir(parents=True, exist_ok=False)


def export_requests(root: Path, output: Path) -> None:
    check_frozen(root)
    new_output_directory(output)
    cases = read_cases(root)
    write_jsonl(output / "inputs.jsonl", [
        {name: case[name] for name in ("case_id", "input", "input_sha256")}
        for case in cases
    ])
    question_rows = [{
        "case_id": case["case_id"], "query": case["input"]["query"],
        "conditions": json.dumps(case["input"]["conditions"], ensure_ascii=False),
        "decision": "", "reviewer": "", "notes": "",
    } for case in cases]
    write_review_csv(output / "question_review.csv", question_rows, list(question_rows[0]))
    write_json(output / "provenance.json", {"dataset_manifest_sha256": digest(root / "manifest.json")})


def validate_records(
    path: Path,
    cases: list[dict[str, Any]],
    mode: RankingMode,
    corpus_ids: set[int],
) -> dict[str, dict[str, Any]]:
    records = read_jsonl(path)
    indexed = {record["case_id"]: record for record in records}
    if len(indexed) != len(records) or set(indexed) != {case["case_id"] for case in cases}:
        raise ValueError("Each mode requires exactly one response for every holdout question")
    for case in cases:
        record = indexed[case["case_id"]]
        ranked = record.get("ranked_place_ids")
        if record.get("input_sha256") != case["input_sha256"] or record.get("ranking_mode") != mode:
            raise ValueError("Response input hash or ranking mode mismatch")
        if search_record_error(case, record) is not None or not search_quality_observed(record) or record.get("error_type"):
            raise ValueError("Resolve collection failures or unsupported conditions before preparing a complete review")
        if not isinstance(ranked, list) or any(type(identifier) is not int or identifier not in corpus_ids for identifier in ranked):
            raise ValueError("Returned place IDs must belong to the frozen corpus")
        if len(set(ranked)) != len(ranked) or len(ranked) > 20:
            raise ValueError("Returned IDs must be unique and respect response limit 20")
    return indexed


def write_review_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def prepare_review(
    root: Path,
    embedding_path: Path,
    reranking_path: Path,
    output: Path,
) -> None:
    check_frozen(root)
    protocol = read_json(root / "protocol.json")
    cases = read_cases(root)
    corpus = {place["id"]: place for place in read_json(root / protocol["corpus_path"])}
    modes = {
        RankingMode.SEMANTIC_ONLY: validate_records(embedding_path, cases, RankingMode.SEMANTIC_ONLY, set(corpus)),
        RankingMode.RERANKED: validate_records(reranking_path, cases, RankingMode.RERANKED, set(corpus)),
    }
    randomizer = random.Random(REVIEW_SEED)
    review_rows: list[dict[str, Any]] = []
    mapping_rows: list[dict[str, Any]] = []
    question_rows: list[dict[str, Any]] = []
    depth = protocol["comparison"]["review_pool_depth_per_mode"]
    for case in cases:
        case_id = case["case_id"]
        pooled = sorted({identifier for records in modes.values() for identifier in records[case_id]["ranked_place_ids"][:depth]})
        randomizer.shuffle(pooled)
        question_rows.append({
            "case_id": case_id, "query": case["input"]["query"],
            "conditions": json.dumps(case["input"]["conditions"], ensure_ascii=False),
            "pooled_candidate_count": len(pooled), "answerability": "",
            "review_status": ReviewStatus.PENDING, "reviewer": "", "notes": "",
        })
        for ordinal, identifier in enumerate(pooled, 1):
            place = corpus[identifier]
            candidate_key = f"{case_id}-C{ordinal:02d}"
            review_rows.append({
                "case_id": case_id, "candidate_key": candidate_key, "query": case["input"]["query"],
                "conditions": json.dumps(case["input"]["conditions"], ensure_ascii=False),
                "place_name": place["name"], "place_region": place["region"], "place_city": place["city"],
                "description": place["description"], "relevance": "", "evidence": "", "rationale": "",
                "review_status": ReviewStatus.PENDING, "reviewer": "",
            })
            mapping_rows.append({"case_id": case_id, "candidate_key": candidate_key, "place_id": identifier})
    new_output_directory(output)
    write_review_csv(output / "questions.csv", question_rows, list(question_rows[0]))
    candidate_fields = [
        "case_id", "candidate_key", "query", "conditions", "place_name", "place_region", "place_city",
        "description", "relevance", "evidence", "rationale", "review_status", "reviewer",
    ]
    write_review_csv(output / "candidates.csv", review_rows, candidate_fields)
    write_jsonl(output / "private_mapping.jsonl", mapping_rows)
    write_json(output / "review_manifest.json", {
        "status": "pending_human_review", "dataset_manifest_sha256": digest(root / "manifest.json"),
        "response_sha256": {"embedding": digest(embedding_path), "reranking": digest(reranking_path)},
        "case_count": len(cases), "pooled_candidate_count": len(review_rows), "pool_depth_per_mode": depth,
        "review_seed": REVIEW_SEED, "candidate_csv_sha256": digest(output / "candidates.csv"),
        "warning": "Keep private_mapping and original rankings from reviewers. Snapshot text must match the collection corpus. No gold scores have been created.",
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_HOLDOUT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("freeze")
    commands.add_parser("check")
    export = commands.add_parser("export-inputs")
    export.add_argument("--output-dir", type=Path, required=True)
    review = commands.add_parser("prepare-review")
    review.add_argument("--embedding-records", type=Path, required=True)
    review.add_argument("--reranking-records", type=Path, required=True)
    review.add_argument("--output-dir", type=Path, required=True)
    arguments = parser.parse_args()
    if arguments.command == "freeze":
        if (arguments.dataset / "manifest.json").exists():
            raise FileExistsError("A frozen manifest cannot be overwritten")
        write_json(arguments.dataset / "manifest.json", dataset_report(arguments.dataset))
        return
    if arguments.command == "check":
        report = check_frozen(arguments.dataset)
        print(json.dumps({name: report[name] for name in ("dataset_id", "case_count", "counts_by_stratum", "primary_family_count", "human_judgments_complete")}, ensure_ascii=False, indent=2))
        return
    if arguments.command == "export-inputs":
        export_requests(arguments.dataset, arguments.output_dir)
        return
    prepare_review(arguments.dataset, arguments.embedding_records, arguments.reranking_records, arguments.output_dir)


if __name__ == "__main__":
    main()
