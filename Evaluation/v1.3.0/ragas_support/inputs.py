"""Pair real API outputs with CSV judgments and authored reference answers."""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class StrategyVersion(str, Enum):
    SEMANTIC = "v1_semantic_only"
    RERANKED = "v2_reranked"


class ApiExecutionStatus(str, Enum):
    COMPLETED = "completed"


class ConditionCoverage(str, Enum):
    COMPLETE = "complete"


INPUT_FILES = {
    StrategyVersion.SEMANTIC: "api_embedding/v1.jsonl",
    StrategyVersion.RERANKED: "api_reranking/v2.jsonl",
}


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized_ids(values: list[Any], label: str) -> list[str]:
    if not isinstance(values, list) or any(type(value) not in (int, str) for value in values):
        raise ValueError(f"{label}: IDs must be a list of integers or strings")
    normalized = [str(value) for value in values]
    if any(not value.strip() for value in normalized) or len(set(normalized)) != len(normalized):
        raise ValueError(f"{label}: empty or duplicate IDs")
    return normalized


@dataclass
class EvaluationBatch:
    samples_by_version: dict[str, list[dict[str, Any]]]
    skipped: dict[str, int]
    missing_reference_case_ids: list[str]
    review_statuses: list[str]
    input_hashes: dict[str, str]

    @property
    def paired_case_count(self) -> int:
        return len(next(iter(self.samples_by_version.values())))


def load_batch(root: Path) -> EvaluationBatch:
    review_path = root / "review_notes_filled_v1.3.0.csv"
    judgments: dict[str, dict[str, int]] = {}
    review_statuses: set[str] = set()
    with review_path.open(encoding="utf-8-sig", newline="") as stream:
        for row in csv.DictReader(stream):
            if not row["case_id"] or not row["place_id"]:
                continue
            case_id = row["case_id"]
            place_id = str(row["place_id"])
            grade = int(row["relevance"])
            if grade not in range(4) or place_id in judgments.setdefault(case_id, {}):
                raise ValueError(f"{case_id}: invalid or duplicate CSV judgment")
            judgments[case_id][place_id] = grade
            review_statuses.add(row["review_status"])

    references_path = root / "golden.jsonl"
    reference_rows = read_jsonl(references_path) if references_path.exists() else []
    references = {row["case_id"]: row for row in reference_rows}
    if len(references) != len(reference_rows):
        raise ValueError("Duplicate case IDs in golden.jsonl")

    outputs: dict[str, dict[str, dict[str, Any]]] = {}
    hashes = {review_path.name: digest(review_path)}
    if references_path.exists():
        hashes[references_path.name] = digest(references_path)
    for strategy, relative_path in INPUT_FILES.items():
        path = root / relative_path
        rows = read_jsonl(path)
        indexed = {row["case_id"]: row for row in rows}
        if len(indexed) != len(rows):
            raise ValueError(f"{strategy.value}: duplicate API case IDs")
        for case_id, row in indexed.items():
            if row.get("strategy_version") != strategy.value:
                raise ValueError(f"{case_id}: API strategy version mismatch")
        outputs[strategy.value] = indexed
        hashes[relative_path] = digest(path)

    common = set.intersection(*(set(rows) for rows in outputs.values()))
    union = set.union(*(set(rows) for rows in outputs.values()))
    skipped: Counter[str] = Counter({"missing_in_one_version": len(union - common)})
    samples = {version: [] for version in outputs}
    missing_references: list[str] = []

    for case_id in sorted(common):
        paired_rows = {version: rows[case_id] for version, rows in outputs.items()}
        queries = {row.get("user_input", "") for row in paired_rows.values()}
        if len(queries) != 1 or not next(iter(queries)).strip():
            raise ValueError(f"{case_id}: missing or inconsistent API user_input")
        authored = references.get(case_id, {})
        if authored.get("query") is not None and authored["query"] not in queries:
            raise ValueError(f"{case_id}: API input differs from golden query")
        answers = [authored.get("reference"), *(row.get("reference") for row in paired_rows.values())]
        provided = {answer for answer in answers if isinstance(answer, str) and answer.strip()}
        if any(answer is not None and (not isinstance(answer, str) or not answer.strip()) for answer in answers):
            raise ValueError(f"{case_id}: reference must be nonempty text or null")
        if len(provided) > 1:
            raise ValueError(f"{case_id}: conflicting references; synchronize golden and API inputs")
        reference = next(iter(provided), None)
        if reference is None:
            missing_references.append(case_id)

        if any(row.get("execution_status") != ApiExecutionStatus.COMPLETED for row in paired_rows.values()):
            skipped["not_completed"] += 1
            continue
        if any(row.get("condition_coverage") != ConditionCoverage.COMPLETE for row in paired_rows.values()):
            skipped["incomplete_conditions"] += 1
            continue
        case_judgments = judgments.get(case_id, {})
        positives = sorted(place_id for place_id, grade in case_judgments.items() if grade >= 2)
        if not positives:
            skipped["no_relevant_review_ids"] += 1
            continue
        for version, row in paired_rows.items():
            ids = normalized_ids(row.get("retrieved_context_ids", []), case_id)
            contexts = row.get("retrieved_contexts") or []
            if not isinstance(contexts, list) or any(not isinstance(item, str) for item in contexts):
                raise ValueError(f"{case_id}: retrieved_contexts must contain actual text")
            if contexts and len(contexts) != len(ids):
                raise ValueError(f"{case_id}: context text and ID counts differ")
            response = row.get("response")
            if response is not None and not isinstance(response, str):
                raise ValueError(f"{case_id}: response must be actual response text or null")
            samples[version].append({
                "case_id": case_id,
                "strategy_version": version,
                "user_input": row["user_input"],
                "response": response,
                "retrieved_contexts": list(contexts),
                "reference": reference,
                "retrieved_context_ids": list(row["retrieved_context_ids"]),
                "reference_context_ids": [int(value) if value.isdecimal() else value for value in positives],
                "judged_retrieved_context_ids": [original for original, value in zip(row["retrieved_context_ids"], ids) if value in case_judgments],
                "unjudged_retrieved_context_ids": [original for original, value in zip(row["retrieved_context_ids"], ids) if value not in case_judgments],
            })
    return EvaluationBatch(samples, dict(skipped), missing_references, sorted(review_statuses), hashes)
