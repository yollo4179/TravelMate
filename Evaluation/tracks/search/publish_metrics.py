"""Build search summaries from saved observations; publish only through an explicit budget."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, read_jsonl, write_json
from common.execution.control import RunMode, load_control
from common.observability.langsmith_transport import langsmith_transport, publish_artifact
from common.observability.search_records import search_quality_observed


def build_artifact(collection_dir: Path, embedding_run: Path, reranking_run: Path) -> dict[str, Any]:
    collection = read_json(collection_dir / "collection_summary.json")
    runs = {"embedding": embedding_run, "reranking": reranking_run}
    source_hashes = {"collection_summary": digest(collection_dir / "collection_summary.json")}
    cases_by_mode: dict[str, set[str]] = {}
    summaries: dict[str, dict[str, Any]] = {}
    verified = collection.get("execution_mode") == RunMode.LIVE and collection.get("status") == "completed"
    for mode, run in runs.items():
        summary = read_json(run / "summary.json")
        scores = read_jsonl(run / "scores/results.jsonl")
        observations = read_jsonl(run / "outputs/records.jsonl")
        filename = "embedding_records.jsonl" if mode == "embedding" else "reranked_records.jsonl"
        response_path = collection_dir / filename
        if summary.get("responses_sha256") != digest(response_path):
            raise ValueError("Scored responses do not match the original saved collection file")
        original = {row["case_id"]: row for row in read_jsonl(response_path)}
        if len(original) != len(read_jsonl(response_path)) or len({row["case_id"] for row in scores}) != len(scores):
            raise ValueError("Duplicate original observations or scored cases")
        if any(original.get(row["case_id"]) != row for row in observations):
            raise ValueError("Scoring inputs differ from the original HTTP observations")
        cases_by_mode[mode] = {row["case_id"] for row in scores}
        if not cases_by_mode[mode] or cases_by_mode[mode] != {row["case_id"] for row in observations}:
            raise ValueError("Scoring outputs and observed cases must match exactly")
        verified = verified and summary.get("status") == "completed" and all(search_quality_observed(row) for row in observations)
        verified = verified and summary.get("search_quality_evaluated_count") == len(scores)
        if any(row.get("ranking_mode") != ("SEMANTIC_ONLY" if mode == "embedding" else "RERANKED") for row in observations):
            raise ValueError("Original ranking mode differs from the explicit publication source")
        verified = verified and summary.get("dataset_manifest_sha256") == collection.get("dataset_manifest_sha256")
        summaries[mode] = summary
        source_hashes[mode + "_responses"] = digest(response_path)
        source_hashes[mode + "_summary"] = digest(run / "summary.json")
        source_hashes[mode + "_scores"] = digest(run / "scores/results.jsonl")
    if cases_by_mode["embedding"] != cases_by_mode["reranking"]:
        raise ValueError("Paired publication requires the same explicitly scored cases")
    metrics = {mode + "." + name: value["mean"] for mode, summary in summaries.items() for name, value in summary["code_metrics_and_gpt_scores"].items() if value.get("evaluated_count", 0) > 0}
    return {
        "case_ids": sorted(cases_by_mode["embedding"]),
        "quality_status": "verified_search_observations" if verified else "not_evaluated",
        "metrics": metrics if verified else {},
        "quality_denominators": {mode: summary["code_metrics_and_gpt_scores"] for mode, summary in summaries.items()},
        "source_sha256": source_hashes,
        "search_execution_mode": collection.get("execution_mode"),
        "latency": collection.get("by_mode"),
        "scope": "Search ranking only; no tool-choice, generated explanation, plan, route or state quality is inferred",
    }


async def publish(arguments: argparse.Namespace) -> None:
    control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
    try:
        artifact = build_artifact(arguments.collection_dir, arguments.embedding_run, arguments.reranking_run)
        expected = control.settings.parameter("source_sha256")
        if artifact["source_sha256"] != expected:
            raise ValueError("Publication source files differ from the explicit configuration")
        write_json(arguments.output_dir / "artifact.json", artifact)
        async with langsmith_transport(control, arguments.api_key_env) as transport:
            receipt = await publish_artifact(control, transport, name="travelmate.search.metrics.summary", artifact=artifact)
        write_json(arguments.output_dir / "publication.json", receipt)
    except Exception as exception:
        control.reject_result(type(exception).__name__)
        write_json(arguments.output_dir / "failure.json", {**control.summary(), "status": "failed", "error_type": type(exception).__name__})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", type=Path, required=True)
    parser.add_argument("--embedding-run", type=Path, required=True)
    parser.add_argument("--reranking-run", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default="LANGSMITH_API_KEY")
    asyncio.run(publish(parser.parse_args()))


if __name__ == "__main__":
    main()
