"""Collect paired live Spring search responses for the V1.4 search track."""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
from enum import StrEnum
import json
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any

import httpx
import jwt
from dotenv import load_dotenv
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import inject
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.io import export_inputs, read_json, read_jsonl, write_json, write_jsonl
from common.metrics.ranking import ranking_metrics
from common.paths import DEFAULT_DATASET, EVALUATION_ROOT
from common.runs.run_record import allocate_run, evaluator_git_sha
from common.runs.tracks import Track


class RankingMode(StrEnum):
    SEMANTIC_ONLY = "SEMANTIC_ONLY"
    RERANKED = "RERANKED"


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(records: list[dict[str, Any]]) -> dict[str, float | int | None]:
    durations = [record["duration_ms"] for record in records if record["http_status"] == 200]
    return {
        "successful_count": len(durations),
        "mean_ms": statistics.mean(durations) if durations else None,
        "p50_ms": percentile(durations, 0.5),
        "p95_ms": percentile(durations, 0.95),
    }


def configure_langsmith() -> TracerProvider | None:
    load_dotenv(EVALUATION_ROOT.parent / ".env", override=False)
    load_dotenv(EVALUATION_ROOT.parent / "Docker/build/stack/runtime.env", override=False)
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        return None
    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/")
    project = os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability")
    provider = TracerProvider(resource=Resource.create({"service.name": "travelmate-search-evaluation"}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(
        endpoint=f"{endpoint}/otel/v1/traces",
        headers={"x-api-key": api_key, "Langsmith-Project": project},
        timeout=10,
    )))
    trace.set_tracer_provider(provider)
    return provider


def admin_access_token(admin_uid: str) -> str:
    secret = os.getenv("JWT_SECRET")
    if not secret:
        raise RuntimeError("JWT_SECRET is missing from the local runtime configuration")
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": admin_uid,
        "roles": "ROLE_ADMIN",
        "token_type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=5),
    }, secret, algorithm="HS256")


def unsupported_conditions(conditions: dict[str, Any]) -> list[str]:
    return [name for name in ("exclude_place_ids", "conversation") if conditions.get(name)]


def request_plan_context(area: dict[str, Any]) -> dict[str, Any]:
    center = area["center"]
    now = datetime.now(timezone(timedelta(hours=9))).replace(second=0, microsecond=0)
    if now.hour == 23:
        now -= timedelta(hours=2)
    return {
        "area": {
            "type": "CIRCLE",
            "center": {"lat": center["latitude"], "lon": center["longitude"]},
            "radiusMeters": area["radius_meters"],
            "regionId": None,
        },
        "origin": {
            "coordinate": {"lat": center["latitude"], "lon": center["longitude"]},
            "label": "평가용 선택 지점",
            "source": "SELECTED_POINT",
        },
        "destination": None,
        "startAt": now.isoformat(),
        "endAt": (now + timedelta(hours=1)).isoformat(),
        "transportMode": "WALK",
        "objective": "DISTANCE",
        "preferences": {"themes": [], "avoid": [], "pace": "NORMAL", "partySize": 1, "budgetKrw": None},
        "categoryRequirements": [],
        "additionalRequest": None,
        "unknownHoursPolicy": "ALLOW_WITH_WARNING",
    }


async def request_search(
    client: httpx.AsyncClient,
    *,
    case: dict[str, Any],
    input_sha256: str,
    mode: str,
    admin_uid: str,
    warmup: bool = False,
) -> dict[str, Any]:
    conditions = case["input"]["conditions"]
    query = case["input"]["query"]
    params: dict[str, str | int] = {"rankingMode": mode}
    area = conditions.get("area")
    if area:
        method = "POST"
        route = "/api/v1/places/search"
        body = {"context": request_plan_context(area), "query": query, "limit": 20}
        applied = ["query", "area"]
    else:
        method = "GET"
        route = "/api/places/search"
        body = None
        params.update(query=query, limit=20)
        applied = ["query"]
        for name in ("region", "city", "category"):
            if conditions.get(name) is not None:
                params[name] = conditions[name]
                applied.append(name)
    unsupported = unsupported_conditions(conditions)
    headers = {"Authorization": f"Bearer {admin_access_token(admin_uid)}"}
    inject(headers)
    started = time.perf_counter()
    try:
        response = await client.request(method, route, params=params, json=body, headers=headers)
        elapsed_ms = (time.perf_counter() - started) * 1000
        payload = response.json()
        if not isinstance(payload, list):
            raise ValueError(f"Search API returned {response.status_code} with a non-list payload")
        if any(not isinstance(item, dict) or type(item.get("placeId")) is not int for item in payload):
            raise ValueError("Search API returned a place without an integer placeId")
        status = response.status_code
        error_type = None
    except (httpx.HTTPError, ValueError, json.JSONDecodeError) as exception:
        elapsed_ms = (time.perf_counter() - started) * 1000
        payload = []
        status = response.status_code if "response" in locals() else None
        error_type = type(exception).__name__
    current_span = trace.get_current_span()
    return {
        "case_id": case["case_id"],
        "input_sha256": input_sha256,
        "record_source": "spring_search_api",
        "model": "BAAI/bge-m3 + BAAI/bge-reranker-v2-m3" if mode == RankingMode.RERANKED else "BAAI/bge-m3",
        "ranking_mode": mode,
        "query": query,
        "request_id": case["case_id"] + ":" + mode,
        "trace_id": format(current_span.get_span_context().trace_id, "032x"),
        "http_method": method,
        "http_route": route,
        "http_status": status,
        "duration_ms": round(elapsed_ms, 3),
        "requested_conditions": conditions,
        "applied_condition_fields": applied,
        "unsupported_conditions": unsupported,
        "condition_coverage": "partial" if unsupported else "complete",
        "ranked_place_ids": [item["placeId"] for item in payload],
        "items": payload,
        "error_type": error_type,
        "warmup": warmup,
    }


def set_quality_attributes(case: dict[str, Any], records: dict[str, dict[str, Any]]) -> None:
    span = trace.get_current_span()
    quality_ready = all(record["http_status"] == 200 and record["condition_coverage"] == "complete" for record in records.values())
    span.set_attribute("evaluation.quality_status", "scored" if quality_ready else "excluded")
    if not quality_ready:
        span.set_attribute("evaluation.quality_exclusion_reason", "request_failed_or_conditions_not_fully_applied")
    judgments = {item["place_id"]: item["relevance"] for item in case["place_judgments"]}
    for mode, record in records.items():
        prefix = "embedding" if mode == RankingMode.SEMANTIC_ONLY else "reranking"
        span.set_attribute(f"evaluation.{prefix}.duration_ms", record["duration_ms"])
        span.set_attribute(f"evaluation.{prefix}.returned_count", len(record["ranked_place_ids"]))
        span.set_attribute(f"evaluation.{prefix}.condition_coverage", record["condition_coverage"])
        if record["http_status"] != 200 or record["condition_coverage"] != "complete":
            continue
        for name, value in ranking_metrics(record["ranked_place_ids"], judgments).items():
            span.set_attribute(f"evaluation.{prefix}.{name}", value)


async def collect(args: argparse.Namespace) -> Path:
    provider = configure_langsmith()
    if provider is None:
        raise RuntimeError("LangSmith API key is missing; trace publishing was requested")
    all_cases = read_jsonl(args.dataset / "generated/golden.jsonl")
    cases = [
        case for case in all_cases
        if "search" in case["evaluation_tracks"]
        and (args.group == "all" or case["evaluation_group"] == args.group)
        and (args.split == "all" or case["split"] == args.split)
    ]
    corpus = {place["id"]: place for place in read_json(args.dataset / "generated/corpus.json")}
    inputs = {row["case_id"]: row for row in export_inputs(
        cases, corpus, persona_profile=read_json(args.dataset / "source/persona/guide_v1.json"),
    )}
    run_id, output = allocate_run(Track.SEARCH, args.dataset, args.output_dir)
    tracer = trace.get_tracer("travelmate.search.evaluation", "1.0.0")
    by_mode: dict[RankingMode, list[dict[str, Any]]] = {
        RankingMode.SEMANTIC_ONLY: [], RankingMode.RERANKED: [],
    }
    warmups: list[dict[str, Any]] = []
    status = "running"
    try:
        async with httpx.AsyncClient(base_url=args.server_url, timeout=args.timeout_seconds) as client:
            for mode in by_mode:
                with tracer.start_as_current_span("travelmate.search.evaluation_warmup") as span:
                    span.set_attribute("evaluation.mode", mode)
                    warmups.append(await request_search(
                        client, case=cases[0], input_sha256=inputs[cases[0]["case_id"]]["input_sha256"],
                        mode=mode, admin_uid=args.admin_uid, warmup=True,
                    ))
            if any(record["http_status"] != 200 for record in warmups):
                raise RuntimeError(f"Warmup search failed: {[record['http_status'] for record in warmups]}")
            for index, case in enumerate(cases, 1):
                with tracer.start_as_current_span("travelmate.search.evaluation_case") as span:
                    span.set_attribute("evaluation.case_id", case["case_id"])
                    span.set_attribute("evaluation.query", case["input"]["query"])
                    span.set_attribute("evaluation.dataset_version", "1.4.0")
                    span.set_attribute("evaluation.split", case["split"])
                    span.set_attribute("evaluation.requested_condition_coverage", "partial" if unsupported_conditions(case["input"]["conditions"]) else "complete")
                    paired: dict[str, dict[str, Any]] = {}
                    modes = list(by_mode) if index % 2 else list(reversed(by_mode))
                    for mode in modes:
                        with tracer.start_as_current_span("travelmate.search.evaluation_request") as request_span:
                            request_span.set_attribute("evaluation.case_id", case["case_id"])
                            request_span.set_attribute("evaluation.mode", mode)
                            record = await request_search(
                                client, case=case, input_sha256=inputs[case["case_id"]]["input_sha256"],
                                mode=mode, admin_uid=args.admin_uid,
                            )
                            request_span.set_attribute("evaluation.duration_ms", record["duration_ms"])
                            request_span.set_attribute("http.response.status_code", record["http_status"] or 0)
                            paired[mode] = record
                            by_mode[mode].append(record)
                    set_quality_attributes(case, paired)
                for mode, records in by_mode.items():
                    filename = "embedding_records.jsonl" if mode == RankingMode.SEMANTIC_ONLY else "reranked_records.jsonl"
                    write_jsonl(output / filename, records)
                print(f"search: {case['case_id']} ({index}/{len(cases)})", flush=True)
        status = "completed"
    finally:
        write_json(output / "collection_summary.json", {
            "status": status,
            "run_id": run_id,
            "dataset_version": args.dataset.name,
            "evaluator_git_sha": evaluator_git_sha(),
            "selected_case_count": len(cases),
            "group": args.group,
            "split": args.split,
            "langsmith_project": os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability"),
            "reranking_configuration": {
                "execution_strategy": os.getenv("RERANK_EXECUTION_STRATEGY", "not_recorded"),
                "batch_size": os.getenv("RERANK_BATCH_SIZE", "not_recorded"),
                "diagnostics_enabled": os.getenv("RERANK_DIAGNOSTICS_ENABLED", "not_recorded"),
                "configuration_source": "local environment; verify against server trace attributes",
            },
            "warmup": [{"mode": row["ranking_mode"], "http_status": row["http_status"], "duration_ms": row["duration_ms"]} for row in warmups],
            "by_mode": {
                mode: {
                    "request_count": len(records),
                    "fully_applied_count": sum(record["condition_coverage"] == "complete" and record["http_status"] == 200 for record in records),
                    "partial_condition_count": sum(record["condition_coverage"] == "partial" for record in records),
                    "latency": latency_summary(records),
                } for mode, records in by_mode.items()
            },
            "notes": [
                "Only real Spring search API responses are recorded; no agent envelope or tool calls are fabricated.",
                "Missing exclude_place_ids or conversation support is marked partial and excluded from full-condition quality means.",
                "The server performs a fresh top-30 pgvector search for each mode; a byte-identical candidate pool is not proven by this API.",
                "LLM response latency and agent quality are outside this search-only run.",
            ],
        })
        provider.force_flush(timeout_millis=30000)
        provider.shutdown()
    return output


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", choices=("development", "test", "all"), default="all")
    parser.add_argument("--group", choices=("plannerLLM", "managerLLM", "all"), default="plannerLLM")
    parser.add_argument("--admin-uid", required=True)
    parser.add_argument("--server-url", default="http://127.0.0.1:8080")
    parser.add_argument("--timeout-seconds", type=float, default=180.0)
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    output = asyncio.run(collect(args))
    print(f"Collected live search records: {output}")


if __name__ == "__main__":
    main()
