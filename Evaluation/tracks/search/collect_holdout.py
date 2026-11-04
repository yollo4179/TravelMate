"""Collect frozen holdout queries without calculating scores before human judgment."""
from __future__ import annotations

import argparse
import asyncio
import csv
from enum import StrEnum
import json
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, write_json, write_jsonl
from tracks.search.holdout import DEFAULT_HOLDOUT, check_frozen, new_output_directory, read_cases


class QuestionDecision(StrEnum):
    ACCEPT = "accept"


class CollectionStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    PARTIAL = "partial"
    FAILED = "failed"


def check_question_review(path: Path, cases: list[dict[str, Any]]) -> None:
    with path.open(encoding="utf-8-sig", newline="") as source:
        reviews = list(csv.DictReader(source))
    indexed = {row["case_id"]: row for row in reviews}
    if len(indexed) != len(reviews) or set(indexed) != {case["case_id"] for case in cases}:
        raise ValueError("Question review must cover every unique holdout question")
    for case in cases:
        review = indexed[case["case_id"]]
        if review["decision"] != QuestionDecision.ACCEPT or not review["reviewer"].strip():
            raise ValueError("Human question review must be accepted before holdout collection")
        if review["query"] != case["input"]["query"] or json.loads(review["conditions"]) != case["input"]["conditions"]:
            raise ValueError("Reviewed questions or conditions differ from frozen inputs")


async def collect(arguments: argparse.Namespace) -> None:
    check_frozen(arguments.dataset)
    cases = read_cases(arguments.dataset)
    check_question_review(arguments.question_review, cases)
    runtime = read_json(arguments.runtime_record)
    required = {"embedding_revision", "reranker_revision", "gpu", "corpus_verified", "configuration_verified"}
    if not required <= runtime.keys() or any(not runtime[name] for name in required):
        raise ValueError("Runtime record needs actual model revisions, GPU and confirmed corpus/configuration checks")
    if runtime["corpus_verified"] is not True or runtime["configuration_verified"] is not True:
        raise ValueError("Runtime corpus and configuration checks must be boolean true")

    import httpx
    from opentelemetry import trace
    from tracks.search.collect_live import RankingMode, configure_langsmith, latency_summary, request_search

    new_output_directory(arguments.output_dir)
    provider = configure_langsmith()
    tracer = trace.get_tracer("travelmate.search.holdout", "1.0.0")
    records: dict[RankingMode, list[dict[str, Any]]] = {mode: [] for mode in RankingMode}
    summary = {
        "status": CollectionStatus.RUNNING, "quality_status": "pending_human_judgments",
        "dataset_manifest_sha256": digest(arguments.dataset / "manifest.json"),
        "question_review_sha256": digest(arguments.question_review),
        "runtime_record": runtime, "runtime_record_sha256": digest(arguments.runtime_record),
        "comparison": read_json(arguments.dataset / "protocol.json")["comparison"],
        "candidate_pool_parity": "Fresh retrieval per mode; byte-identical candidates not established",
    }
    write_json(arguments.output_dir / "collection_summary.json", summary)
    try:
        async with httpx.AsyncClient(base_url=arguments.server_url, timeout=arguments.timeout_seconds) as client:
            for index, case in enumerate(cases):
                order = list(RankingMode)
                if index % 2:
                    order.reverse()
                for mode in order:
                    with tracer.start_as_current_span("travelmate.search.holdout.request") as span:
                        span.set_attribute("evaluation.dataset", arguments.dataset.name)
                        span.set_attribute("evaluation.case_id", case["case_id"])
                        span.set_attribute("evaluation.mode", mode.value)
                        records[mode].append(await request_search(
                            client,
                            case=case,
                            input_sha256=case["input_sha256"],
                            mode=mode,
                            admin_uid=arguments.admin_uid,
                        ))
                write_jsonl(arguments.output_dir / "embedding_records.jsonl", records[RankingMode.SEMANTIC_ONLY])
                write_jsonl(arguments.output_dir / "reranked_records.jsonl", records[RankingMode.RERANKED])
                print(f"Collected {index + 1}/{len(cases)} holdout questions", flush=True)
        successful = all(
            row["http_status"] == 200 and row["condition_coverage"] == "complete" and not row["error_type"]
            for rows in records.values() for row in rows
        )
        summary["status"] = CollectionStatus.COMPLETED if successful else CollectionStatus.PARTIAL
    except Exception:
        summary["status"] = CollectionStatus.FAILED
        raise
    finally:
        summary["by_mode"] = {mode.value: latency_summary(rows) for mode, rows in records.items()}
        summary["latency_policy"] = "No warmup excluded; first-call and later latency are retained together. This is a quality collection, not a latency benchmark."
        write_json(arguments.output_dir / "collection_summary.json", summary)
        if provider is not None:
            provider.force_flush(timeout_millis=30000)
            provider.shutdown()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_HOLDOUT)
    parser.add_argument("--question-review", type=Path, required=True)
    parser.add_argument("--runtime-record", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--admin-uid", required=True)
    parser.add_argument("--server-url", default="http://localhost:8080")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
