"""Create a new frozen question version from explicit human accept/deny decisions."""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from enum import StrEnum
import json
from pathlib import Path
import shutil
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, write_json
from tracks.search.holdout import (
    DEFAULT_HOLDOUT,
    check_frozen,
    dataset_report,
    read_cases,
    write_review_csv,
)


class ReviewDecision(StrEnum):
    ACCEPT = "accept"
    DENY = "deny"


def reviewed_questions(
    source_dataset: Path,
    review_path: Path,
) -> list[dict[str, str]]:
    check_frozen(source_dataset)
    cases = {case["case_id"]: case for case in read_cases(source_dataset)}
    with review_path.open(encoding="utf-8-sig", newline="") as source:
        reviews = list(csv.DictReader(source))
    if len(reviews) != len(cases) or {row["case_id"] for row in reviews} != set(cases):
        raise ValueError("Every source question requires exactly one explicit review")
    for review in reviews:
        identifier = review["case_id"]
        if not review["decision"].strip() or not review["reviewer"].strip():
            raise ValueError(f"{identifier}: decision or reviewer is still missing")
        ReviewDecision(review["decision"])
        expected = cases[identifier]["input"]
        if review["query"] != expected["query"] or json.loads(review["conditions"]) != expected["conditions"]:
            raise ValueError(f"{identifier}: edited question requires explicit revision handling")
    return reviews


def finalize_review(
    source_dataset: Path,
    review_path: Path,
    target_dataset: Path,
) -> dict[str, Any]:
    reviews = reviewed_questions(source_dataset, review_path)
    accepted = [row for row in reviews if row["decision"] == ReviewDecision.ACCEPT]
    accepted_ids = {row["case_id"] for row in accepted}
    if not accepted_ids:
        raise ValueError("A reviewed dataset needs accepted questions")
    if target_dataset.resolve().parent != source_dataset.resolve().parent:
        raise ValueError("The reviewed dataset must be a new sibling version")
    if target_dataset.exists():
        raise FileExistsError("A reviewed version cannot overwrite an existing directory")
    with (source_dataset / "source/questions.csv").open(encoding="utf-8-sig", newline="") as source:
        questions = [row for row in csv.DictReader(source) if row["case_id"] in accepted_ids]
    protocol = read_json(source_dataset / "protocol.json")
    protocol.update(
        dataset_id=target_dataset.name,
        lifecycle="questions_human_reviewed_pending_place_judgments",
        authorship="AI-authored questions reviewed by the user before retrieval; place judgments pending",
        case_counts=dict(Counter(row["stratum"] for row in questions)),
        query_types=list(dict.fromkeys(row["query_type"] for row in questions)),
    )
    original_families = read_json(source_dataset / "source/families.json")
    families = {
        name: filtered
        for name, identifiers in original_families.items()
        if (filtered := [identifier for identifier in identifiers if identifier in accepted_ids])
    }
    changes = {
        "source_dataset": source_dataset.name,
        "source_manifest_sha256": digest(source_dataset / "manifest.json"),
        "human_review_sha256": digest(review_path),
        "counts_by_decision": dict(Counter(row["decision"] for row in reviews)),
        "accepted_case_ids": [row["case_id"] for row in accepted],
        "excluded_case_ids": [row["case_id"] for row in reviews if row["decision"] == ReviewDecision.DENY],
        "query_text_changes": [],
        "policy": "Explicit human decisions only; no retrieval outcomes were used to select questions",
    }
    (target_dataset / "source").mkdir(parents=True, exist_ok=False)
    write_review_csv(target_dataset / "source/questions.csv", questions, list(questions[0]))
    write_review_csv(target_dataset / "source/question_review.csv", accepted, list(accepted[0]))
    shutil.copy2(review_path, target_dataset / "source/original_question_review.csv")
    shutil.copy2(source_dataset / "rubric.md", target_dataset / "rubric.md")
    write_json(target_dataset / "source/families.json", families)
    write_json(target_dataset / "source/review_changes.json", changes)
    write_json(target_dataset / "protocol.json", protocol)
    (target_dataset / "README.md").write_text(
        f"# 사람 질문 검수를 반영한 검색 평가셋 {target_dataset.name}\n\n"
        f"원본 [{source_dataset.name}](../{source_dataset.name}/README.md)의 질문 검수를 반영했다.\n"
        f"총 {len(questions)}문항이며 구성은 `{protocol['case_counts']}`다.\n"
        "제외 문항과 원래 검수표는 `source/review_changes.json`과 `source/original_question_review.csv`에 보존했다.\n"
        "문항을 임의로 승인하거나 문장을 수정하지 않았다. 장소 적합도 판정은 아직 하지 않았다.\n\n"
        "조용한 곳·여유로운 산책처럼 주관적이지만 자연스러운 질문도 유지한다.\n"
        "소음·혼잡도 근거가 부족하면 장소 판정에서 unknown으로 남기며 질문을 억지로 구체화하지 않는다.\n\n"
        "원본 안내의 명령에는 반드시 이 디렉터리를 `--dataset`으로 지정한다.\n"
        "수집 시 `--question-review`에는 이 버전의 `source/question_review.csv`를 사용한다.\n"
        "모델·배치 설정과 동결 코퍼스는 원본 프로토콜을 유지한다.\n",
        encoding="utf-8",
        newline="\n",
    )
    report = dataset_report(target_dataset)
    write_json(target_dataset / "manifest.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dataset", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--question-review", type=Path, required=True)
    parser.add_argument("--output-dataset", type=Path, required=True)
    arguments = parser.parse_args()
    report = finalize_review(arguments.source_dataset, arguments.question_review, arguments.output_dataset)
    print(json.dumps({name: report[name] for name in ("dataset_id", "case_count", "counts_by_stratum")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
