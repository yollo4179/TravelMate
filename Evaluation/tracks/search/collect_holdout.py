"""Reuse independent HTTP collection only for explicitly selected, reviewed frozen cases."""
from __future__ import annotations

import argparse
import asyncio
import csv
from enum import StrEnum
import json
import os
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json
from common.execution.control import ExecutionBlocked, RunMode, load_control
from tracks.search.collect_live import collect_cases
from tracks.search.holdout import check_frozen, read_cases


class QuestionDecision(StrEnum):
    ACCEPT = "accept"


def check_question_review(path: Path, cases: list[dict[str, Any]]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reviews = list(csv.DictReader(source))
    indexed = {row["case_id"]: row for row in reviews}
    if len(indexed) != len(reviews) or not {case["case_id"] for case in cases} <= indexed.keys():
        raise ValueError("Every selected case requires one explicit review")
    for case in cases:
        review = indexed[case["case_id"]]
        if review["decision"] != QuestionDecision.ACCEPT or not review["reviewer"].strip():
            raise ValueError("Human question review must be accepted before collection")
        if review["query"] != case["input"]["query"] or json.loads(review["conditions"]) != case["input"]["conditions"]:
            raise ValueError("Reviewed questions or conditions differ from frozen inputs")


async def collect(arguments: argparse.Namespace) -> None:
    check_frozen(arguments.dataset)
    if arguments.output_dir.exists():
        raise FileExistsError("Collection must not overwrite saved evidence")
    control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
    all_cases = {case["case_id"]: case for case in read_cases(arguments.dataset)}
    if not set(control.settings.case_ids) <= all_cases.keys():
        raise ValueError("Select existing frozen holdout IDs only")
    cases = [all_cases[identifier] for identifier in control.settings.case_ids]
    check_question_review(arguments.question_review, cases)
    if digest(arguments.question_review) != control.settings.parameter("question_review_sha256"):
        raise ValueError("Question review differs from the configured evidence")
    runtime = read_json(arguments.runtime_record)
    if digest(arguments.runtime_record) != control.settings.parameter("runtime_record_sha256"):
        raise ValueError("Runtime evidence differs from the configured evidence")
    if control.settings.mode == RunMode.MOCK:
        await collect_cases(cases=cases, dataset=arguments.dataset, output=arguments.output_dir, control=control, runtime=runtime)
        if control.stopped:
            raise ExecutionBlocked("Collection stopped; partial records are preserved")
        return
    import httpx
    access_token = os.environ[arguments.token_env]
    async with httpx.AsyncClient(timeout=control.settings.timeout_seconds, follow_redirects=False, trust_env=False) as client:
        await collect_cases(cases=cases, dataset=arguments.dataset, output=arguments.output_dir, control=control, runtime=runtime, client=client, access_token=access_token)
    if control.stopped:
        raise ExecutionBlocked("Collection stopped; partial records are preserved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--question-review", type=Path, required=True)
    parser.add_argument("--runtime-record", type=Path, required=True)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--token-env", default="TRAVELMATE_EVAL_ACCESS_TOKEN")
    parser.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
