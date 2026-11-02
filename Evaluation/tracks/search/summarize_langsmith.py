"""Summarize saved trace spans or read bounded pages; missing stages remain unobserved."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
import re
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, read_jsonl, write_json
from common.execution.control import Operation, RunControl, RunMode, load_control
from common.observability.langsmith_transport import LangSmithTransport, langsmith_transport
from common.paths import EVALUATION_ROOT
from tracks.search.collect_live import percentile

DATABASE_STAGES = frozenset({"database.pgvector_search", "database.contextual_evidence_search"})
STAGE_NAMES = DATABASE_STAGES | frozenset({"travelmate.search", "recommendation.kafka_roundtrip", "recommendation.worker_queue", "recommendation.pipeline", "embedding.model_inference", "reranking.model_inference", "reranking.tokenize", "reranking.gpu_transfer", "reranking.model_forward", "reranking.output"})


def trace_id_for(record: dict[str, Any]) -> str | None:
    parent = record.get("http_request", {}).get("traceparent")
    if isinstance(parent, str) and re.fullmatch(r"00-[0-9a-f]{32}-[0-9a-f]{16}-0[01]", parent):
        return parent.split("-")[1]
    observed = record.get("trace_id")
    return observed if isinstance(observed, str) and re.fullmatch(r"(?!0{32}$)[0-9a-f]{32}", observed) else None


def span_duration(run: dict[str, Any]) -> float | None:
    try:
        start = datetime.fromisoformat(run["start_time"].replace("Z", "+00:00"))
        end = datetime.fromisoformat(run["end_time"].replace("Z", "+00:00"))
        elapsed = (end - start).total_seconds() * 1000
        return elapsed if elapsed >= 0 and start.tzinfo is not None and end.tzinfo is not None else None
    except (KeyError, TypeError, ValueError):
        return None


def summarize_records(records: list[dict[str, Any]], capture: dict[str, Any]) -> dict[str, Any]:
    requested = {trace_id_for(record) for record in records} - {None}
    runs = capture.get("runs") or []
    indexed = {run["id"]: run for run in runs}
    if len(indexed) != len(runs):
        raise ValueError("Captured span IDs must be unique; repeated pages are not additional observations")
    groups: dict[tuple[str, str, str, str, str], list[float]] = defaultdict(list)
    observed_stages: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    missing_duration = Counter()
    failed = Counter()
    unknown_names = Counter()
    for run in runs:
        metadata = (run.get("extra") or {}).get("metadata") or {}
        trace_id = metadata.get("OTEL_TRACE_ID")
        if trace_id not in requested:
            continue
        seen.add(trace_id)
        name = run.get("name")
        if name not in STAGE_NAMES:
            unknown_names[str(name)] += 1
            continue
        if run.get("error"):
            failed[name] += 1
            continue
        duration = span_duration(run)
        if duration is None:
            missing_duration[name] += 1
            continue
        device = metadata.get("otel.span.reranking.device") or metadata.get("otel.span.embedding.device") or "not_observed"
        dtype = metadata.get("otel.span.reranking.parameter_dtype") or "not_observed"
        execution = metadata.get("otel.span.reranking.execution_mode") or "not_observed"
        autocast = metadata.get("otel.span.reranking.autocast.dtype") or "not_observed"
        groups[(name, str(device), str(dtype), str(execution), str(autocast))].append(duration)
        observed_stages[trace_id].add(name)
        if name in DATABASE_STAGES:
            observed_stages[trace_id].add("database.retrieval")
    live = capture.get("execution_mode") == RunMode.LIVE and all(record.get("execution_mode") == RunMode.LIVE and record.get("execution_status") == "completed" for record in records)
    stage_rows = [{"stage": name, "device": device, "parameter_dtype": dtype, "execution_strategy": execution, "autocast_dtype": autocast, "count": len(values), "mean_ms": sum(values) / len(values), "p50_ms": percentile(values, 0.5), "p95_ms": percentile(values, 0.95)} for (name, device, dtype, execution, autocast), values in groups.items()]
    missing_bindings = [record["case_id"] for record in records if trace_id_for(record) is None]
    expected_stages: dict[str, set[str]] = defaultdict(set)
    trace_counts = Counter(trace_id_for(record) for record in records if trace_id_for(record))
    for record in records:
        trace = trace_id_for(record)
        if trace is not None:
            expected_stages[trace].update({"travelmate.search", "embedding.model_inference", "database.retrieval"})
            if record.get("ranking_mode") == "RERANKED":
                expected_stages[trace].add("reranking.model_inference")
    missing_stages = {trace: sorted(names - observed_stages[trace]) for trace, names in expected_stages.items() if names - observed_stages[trace]}
    ambiguous = [trace for trace, count in trace_counts.items() if count > 1]
    complete = bool(requested) and not missing_bindings and seen == requested and not capture.get("truncated") and not missing_duration and not failed and not missing_stages and not ambiguous
    return {
        "status": "completed" if live and complete else "partial",
        "execution_mode": capture.get("execution_mode"),
        "case_ids": sorted({record["case_id"] for record in records}),
        "requested_trace_count": len(requested), "observed_trace_count": len(seen),
        "missing_trace_ids": sorted(requested - seen), "cases_without_trace_binding": missing_bindings,
        "live_stage_latency": stage_rows if live else [], "mock_or_unverified_stage_rows": [] if live else stage_rows,
        "missing_duration_by_stage": dict(missing_duration), "failed_spans_by_stage": dict(failed),
        "missing_stages_by_trace": missing_stages, "ambiguous_trace_ids": ambiguous,
        "unrecognized_span_names": dict(unknown_names), "truncated": bool(capture.get("truncated")),
        "notes": ["No model/search/judge is invoked by span aggregation.", "Missing trace IDs, spans, devices, dtypes or timestamps are not filled with successful observations.", "Device/dtype profiles are kept separate; unknown profiles do not prove GPU execution.", "Span durations can overlap and are not summed into fabricated request latency."],
    }


async def query_runs(control: RunControl, transport: LangSmithTransport, records: list[dict[str, Any]]) -> dict[str, Any]:
    control.settings.require_scope(list(dict.fromkeys(record["case_id"] for record in records)))
    pages = control.settings.parameter("max_pages")
    size = control.settings.parameter("page_size")
    if type(pages) is not int or pages < 1 or type(size) is not int or not 1 <= size <= 100:
        raise ValueError("Explicit positive page limits and page_size within 1..100 are required")
    control.settings.require_capacity(Operation.OBSERVATION_READ, pages)
    if not any(trace_id_for(record) for record in records):
        return {"execution_mode": control.settings.mode.value, "runs": [], "truncated": False}
    cursor = None
    seen_cursors: set[str] = set()
    runs: list[dict[str, Any]] = []
    for _ in range(pages):
        payload = {"session": [control.settings.parameter("project_id")], "filter": control.settings.parameter("query_filter"), "limit": size}
        if cursor is not None:
            payload["cursor"] = cursor
        response = await transport.request(Operation.OBSERVATION_READ, control.settings.case_ids[0], "POST", "/runs/query", payload)
        if not isinstance(response.get("runs"), list):
            control.reject_result("InvalidSpanQueryResponse")
            raise ValueError("Span query returned no runs array")
        runs.extend(response["runs"])
        cursor = (response.get("cursors") or {}).get("next")
        if cursor is None:
            return {"execution_mode": control.settings.mode.value, "runs": runs, "truncated": False}
        if cursor in seen_cursors:
            control.reject_result("RepeatedSpanCursor")
            raise ValueError("A repeated cursor is not retried")
        seen_cursors.add(cursor)
    return {"execution_mode": control.settings.mode.value, "runs": runs, "truncated": True}


async def summarize(arguments: argparse.Namespace) -> None:
    records = read_jsonl(arguments.records)
    if arguments.runs_json is not None:
        if arguments.output_dir.exists() or arguments.output_dir.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
            raise FileExistsError("Offline span summary needs a fresh output directory")
        capture = read_json(arguments.runs_json)
        report = summarize_records(records, capture)
        report.update(source_sha256={"records": digest(arguments.records), "span_capture": digest(arguments.runs_json)}, capture_method="offline_saved_capture")
        write_json(arguments.output_dir / "span_summary.json", report)
        return
    control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
    if digest(arguments.records) != control.settings.parameter("records_sha256"):
        raise ValueError("Span source observations differ from the explicit configuration")
    try:
        async with langsmith_transport(control, arguments.api_key_env) as transport:
            capture = await query_runs(control, transport, records)
        write_json(arguments.output_dir / "span_capture.json", capture)
        write_json(arguments.output_dir / "span_summary.json", {**summarize_records(records, capture), "execution": control.summary(), "source_records_sha256": digest(arguments.records)})
    except Exception as exception:
        control.reject_result(type(exception).__name__)
        write_json(arguments.output_dir / "failure.json", {**control.summary(), "status": "failed", "error_type": type(exception).__name__})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--runs-json", type=Path)
    source.add_argument("--config", type=Path)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default="LANGSMITH_API_KEY")
    asyncio.run(summarize(parser.parse_args()))


if __name__ == "__main__":
    main()
