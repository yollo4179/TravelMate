"""Summarize stage timing from LangSmith spans for a live search collection."""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import sys
from typing import Any

from dotenv import load_dotenv
from langsmith import Client

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.io import read_jsonl, write_json
from common.paths import EVALUATION_ROOT
from tracks.search.collect_live import latency_summary


STAGE_NAMES = (
    "travelmate.search",
    "recommendation.kafka_roundtrip",
    "recommendation.worker_queue",
    "recommendation.pipeline",
    "embedding.model_inference",
    "database.pgvector_search",
    "reranking.model_inference",
    "reranking.tokenize",
    "reranking.gpu_transfer",
    "reranking.model_forward",
    "reranking.output",
)


def descendants(root_id: Any, children: dict[Any, list[Any]]) -> list[Any]:
    pending = list(children.get(root_id, []))
    found = []
    while pending:
        child = pending.pop()
        found.append(child)
        pending.extend(children.get(child.id, []))
    return found


def duration_ms(run: Any) -> float | None:
    if run.start_time is None or run.end_time is None:
        return None
    return (run.end_time - run.start_time).total_seconds() * 1000


def summarize(collection_dir: Path) -> dict[str, Any]:
    load_dotenv(EVALUATION_ROOT.parent / ".env", override=False)
    load_dotenv(EVALUATION_ROOT.parent / "Docker/build/stack/runtime.env", override=False)
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        raise RuntimeError("LangSmith API key is missing")
    project = os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability")
    records = [
        *read_jsonl(collection_dir / "embedding_records.jsonl"),
        *read_jsonl(collection_dir / "reranked_records.jsonl"),
    ]
    requested_trace_ids = {record["trace_id"] for record in records}
    started_at = datetime.strptime(collection_dir.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    client = Client(
        api_key=api_key,
        api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
    )
    runs = [
        run for run in client.list_runs(project_name=project, start_time=started_at - timedelta(minutes=1))
        if (run.extra or {}).get("metadata", {}).get("OTEL_TRACE_ID") in requested_trace_ids
    ]
    grouped: dict[str, list[Any]] = defaultdict(list)
    for run in runs:
        grouped[run.extra["metadata"]["OTEL_TRACE_ID"]].append(run)
    timings: dict[str, dict[str, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    trace_urls: dict[str, str] = {}
    runtime_settings: dict[tuple[Any, ...], int] = defaultdict(int)
    runtime_fields = ("reranking.execution_mode", "reranking.batch_size", "reranking.device", "reranking.parameter_dtype", "reranking.autocast.enabled", "reranking.autocast.dtype")
    for run in runs:
        if run.name == "reranking.model_inference":
            metadata = (run.extra or {}).get("metadata", {})
            runtime_settings[tuple(metadata.get("otel.span." + name) for name in runtime_fields)] += 1
    for trace_id, trace_runs in grouped.items():
        children: dict[Any, list[Any]] = defaultdict(list)
        for run in trace_runs:
            children[run.parent_run_id].append(run)
        root_run = next((run for run in trace_runs if run.name == "travelmate.search.evaluation_case"), None)
        if root_run is not None and root_run.extra["metadata"].get("otel.span.evaluation.requested_condition_coverage") == "complete":
            trace_urls[trace_id] = client.get_run_url(run=root_run, project_name=project)
        for request in (run for run in trace_runs if run.name == "travelmate.search.evaluation_request"):
            mode = request.extra["metadata"].get("otel.span.evaluation.mode")
            case_id = request.extra["metadata"].get("otel.span.evaluation.case_id")
            if not mode or not case_id:
                continue
            for child in descendants(request.id, children):
                if child.name not in STAGE_NAMES:
                    continue
                elapsed = duration_ms(child)
                if elapsed is None:
                    continue
                timings[mode][child.name].append({
                    "case_id": case_id,
                    "http_status": 200,
                    "duration_ms": round(elapsed, 3),
                })
    report = {
        "status": "completed" if len(grouped) == len(requested_trace_ids) else "partial",
        "langsmith_project": project,
        "requested_trace_count": len(requested_trace_ids),
        "found_trace_count": len(grouped),
        "found_span_count": len(runs),
        "observed_reranking_configurations": [
            {**dict(zip(runtime_fields, values, strict=True)), "span_count": count}
            for values, count in runtime_settings.items()
        ],
        "by_mode": {
            mode: {name: latency_summary(rows) for name, rows in stage_rows.items()}
            for mode, stage_rows in timings.items()
        },
        "sample_trace_urls": list(trace_urls.values())[:3],
        "notes": [
            "Kafka roundtrip contains worker queue and pipeline processing; parent and child durations must not be added.",
            "Stage durations are LangSmith span wall times; HTTP request duration is separately recorded in collection_summary.json.",
            "This run has no LLM response stage because only the search API was executed.",
        ],
    }
    write_json(collection_dir / "langsmith_timing_summary.json", report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", type=Path, required=True)
    args = parser.parse_args()
    report = summarize(args.collection_dir)
    print({
        "status": report["status"],
        "found_trace_count": report["found_trace_count"],
        "requested_trace_count": report["requested_trace_count"],
        "found_span_count": report["found_span_count"],
    })


if __name__ == "__main__":
    main()
