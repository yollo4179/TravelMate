"""Collect explicitly selected independent-search HTTP observations; no agent is invoked."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import statistics
import sys
from typing import Any
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, export_inputs, read_json, read_jsonl, write_json, write_jsonl
from common.execution.control import AttemptStatus, ExecutionBlocked, Operation, RunControl, RunMode, load_control
from common.observability.search_records import SEARCH_RECORD_VERSION, SEARCH_SOURCE, search_record_error
from common.paths import DEFAULT_DATASET
from common.runs.run_record import evaluator_git_sha
from tracks.search.api_contract import RankingMode, search_body, unsupported_conditions


def percentile(values: list[float], percent: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = (len(ordered) - 1) * percent
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    return ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower)


def latency_summary(records: list[dict[str, Any]]) -> dict[str, float | int | None]:
    durations = [record["duration_ms"] for record in records if record.get("execution_mode") == RunMode.LIVE and record.get("execution_status") == AttemptStatus.COMPLETED]
    return {"successful_live_count": len(durations), "mean_ms": statistics.mean(durations) if durations else None, "p50_ms": percentile(durations, 0.5), "p95_ms": percentile(durations, 0.95)}


async def request_search(
    client: Any,
    *,
    case: dict[str, Any],
    input_sha256: str,
    mode: RankingMode,
    control: RunControl,
    server_url: str,
    limit: int,
    runtime: dict[str, Any],
    access_token: str | None = None,
) -> dict[str, Any]:
    body = search_body(case, mode, limit)
    raw_body = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    request = {"method": "POST", "url": server_url.rstrip("/") + "/api/places/search", "route": "/api/places/search", "raw_body": raw_body, "body_sha256": hashlib.sha256(raw_body.encode("utf-8")).hexdigest()}
    missing = unsupported_conditions(case["input"]["conditions"])
    record: dict[str, Any] = {
        "schema_version": SEARCH_RECORD_VERSION, "record_source": SEARCH_SOURCE,
        "case_id": case["case_id"], "input_sha256": input_sha256,
        "execution_mode": control.settings.mode.value, "execution_status": AttemptStatus.NOT_RUN.value,
        "dispatched": False, "http_request": request, "http_response": None,
        "request_id": None, "request_id_source": "harness_attempt_not_server_identity", "turn_id": None, "job_ids": [],
        "attempt_observation": None,
        "ranking_mode": mode.value, "response_limit": limit, "requested_conditions": case["input"]["conditions"],
        "evaluation_projection": {"version": "frozen-search-to-independent-http-v2", "server_body": body},
        "unsupported_conditions": missing, "condition_coverage": "partial" if missing else "complete",
        "ranked_place_ids": None, "items": None, "duration_ms": None,
        "runtime_verification": runtime,
        "observation_coverage": {name: False for name in ("search", "tool_call", "message", "plan", "state", "memory")},
        "quality_status": "mock_regression_only" if control.settings.mode == RunMode.MOCK else "not_evaluated",
        "error_type": None,
    }
    if missing:
        control.stopped = True

    async def dispatch() -> dict[str, Any]:
        headers = {"Content-Type": "application/json"}
        if access_token:
            headers["Authorization"] = "Bearer " + access_token
        response = await client.request("POST", request["url"], content=raw_body.encode("utf-8"), headers=headers)
        return {"status_code": response.status_code, "raw_body": response.text, "server_request_id": response.headers.get("x-request-id"), "traceparent": response.headers.get("traceparent")}

    try:
        response = await control.execute(Operation.SEARCH, case["case_id"], request, dispatch)
        record["http_response"] = response
        items = json.loads(response["raw_body"])
        if response["status_code"] != 200 or not isinstance(items, list):
            raise ValueError("Search HTTP response is not a successful place list")
        identifiers = [item["placeId"] for item in items]
        if any(type(identifier) is not int or identifier <= 0 for identifier in identifiers) or len(identifiers) != len(set(identifiers)) or len(identifiers) > limit:
            raise ValueError("Search returned invalid or duplicated place IDs, or exceeded the requested limit")
        record.update(execution_status=AttemptStatus.COMPLETED.value, items=items, ranked_place_ids=identifiers)
        record["observation_coverage"]["search"] = control.settings.mode == RunMode.LIVE and runtime.get("execution_mode") == RunMode.LIVE and runtime.get("schema_version") == "search-runtime-verification-v2" and all(runtime.get(name) is True for name in ("corpus_verified", "configuration_verified", "search_material_verified"))
        record["quality_status"] = "recorded_not_scored" if record["observation_coverage"]["search"] else record["quality_status"]
    except Exception as exception:
        attempt = control.last_attempt or {}
        record["execution_status"] = AttemptStatus.NOT_RUN.value if attempt.get("status") == AttemptStatus.NOT_RUN else AttemptStatus.FAILED.value
        record["error_type"] = "unsupported_original_conditions" if missing else type(exception).__name__
        control.stopped = True
    finally:
        attempt = control.last_attempt or {}
        record["request_id"] = attempt.get("attempt_id")
        record["attempt_observation"] = attempt
        record["dispatched"] = attempt.get("dispatched", False)
        record["duration_ms"] = attempt.get("duration_ms")
    return record


def selected_v14_inputs(dataset: Path, case_ids: tuple[str, ...]) -> list[dict[str, Any]]:
    cases = {case["case_id"]: case for case in read_jsonl(dataset / "generated/golden.jsonl") if "search" in case["evaluation_tracks"]}
    if not set(case_ids) <= cases.keys():
        raise ValueError("The configuration must select existing search cases only")
    selected = [cases[identifier] for identifier in case_ids]
    corpus = {place["id"]: place for place in read_json(dataset / "generated/corpus.json")}
    exported = {row["case_id"]: row for row in export_inputs(selected, corpus, persona_profile=read_json(dataset / "source/persona/guide_v1.json"))}
    return [{**case, "input_sha256": exported[case["case_id"]]["input_sha256"]} for case in selected]


async def collect_cases(
    *,
    cases: list[dict[str, Any]],
    dataset: Path,
    output: Path,
    control: RunControl,
    runtime: dict[str, Any],
    client: Any = None,
    access_token: str | None = None,
) -> None:
    control.settings.require_scope([case["case_id"] for case in cases])
    modes = [RankingMode(value) for value in control.settings.parameter("ranking_modes")]
    if not modes or len(modes) != len(set(modes)):
        raise ValueError("Explicit, unique ranking modes are required")
    control.settings.require_capacity(Operation.SEARCH, len(cases) * len(modes))
    expected_manifest = control.settings.parameter("dataset_manifest_sha256")
    if digest(dataset / "manifest.json") != expected_manifest:
        raise ValueError("Dataset manifest differs from the explicit execution configuration")
    protocol = read_json(dataset / "protocol.json") if (dataset / "protocol.json").exists() else None
    corpus_path = dataset / protocol["corpus_path"] if protocol else dataset / "generated/corpus.json"
    if runtime.get("corpus_sha256") != digest(corpus_path):
        raise ExecutionBlocked("Runtime evidence is not bound to the selected frozen corpus")
    require_comparable = control.settings.parameter("require_comparable_runtime")
    if type(require_comparable) is not bool:
        raise ValueError("require_comparable_runtime must be an explicit boolean")
    if require_comparable and (runtime.get("execution_mode") != RunMode.LIVE or not all(runtime.get(name) is True for name in ("corpus_verified", "configuration_verified", "search_material_verified"))):
        raise ExecutionBlocked("Comparable LIVE corpus, configuration and search-material evidence is required")
    records: dict[RankingMode, list[dict[str, Any]]] = {mode: [] for mode in modes}
    write_json(output / "collection_summary.json", {**control.summary(), "status": AttemptStatus.NOT_RUN.value})
    try:
        for case in cases:
            for mode in modes:
                record = await request_search(
                    client,
                    case=case,
                    input_sha256=case["input_sha256"],
                    mode=mode,
                    control=control,
                    server_url=control.settings.parameter("server_url"),
                    limit=control.settings.parameter("response_limit"),
                    runtime=runtime,
                    access_token=access_token,
                )
                records[mode].append(record)
                filename = "embedding_records.jsonl" if mode == RankingMode.SEMANTIC_ONLY else "reranked_records.jsonl"
                write_jsonl(output / filename, records[mode])
    finally:
        write_json(output / "collection_summary.json", {
            **control.summary(),
            "status": "partial" if control.stopped else "completed",
            "evaluator_git_sha": evaluator_git_sha(), "dataset_manifest_sha256": expected_manifest,
            "selected_case_ids": list(control.settings.case_ids),
            "recorded_case_modes": sum(len(rows) for rows in records.values()),
            "not_run_case_modes": [{"case_id": case["case_id"], "ranking_mode": mode.value} for case in cases for mode in modes if not any(row["case_id"] == case["case_id"] for row in records[mode])],
            "quality_status": "mock_regression_only" if control.settings.mode == RunMode.MOCK else "recorded_not_scored",
            "by_mode": {mode.value: latency_summary(rows) for mode, rows in records.items()},
            "notes": ["No agent tool calls, generated explanations, plan outputs, or unobserved successes are synthesized.", "Each ranking mode retrieves independently; candidate parity is not established.", "No warmup, retry, judge, or automatic trace publication is performed."],
        })


async def collect(arguments: argparse.Namespace) -> None:
    if arguments.output_dir.exists():
        raise FileExistsError("Collection outputs cannot overwrite existing evidence")
    control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
    cases = selected_v14_inputs(arguments.dataset, control.settings.case_ids)
    runtime = read_json(arguments.runtime_record)
    if digest(arguments.runtime_record) != control.settings.parameter("runtime_record_sha256"):
        raise ValueError("Runtime evidence differs from the explicit configuration")
    if control.settings.mode == RunMode.MOCK:
        await collect_cases(cases=cases, dataset=arguments.dataset, output=arguments.output_dir, control=control, runtime=runtime)
        if control.stopped:
            raise ExecutionBlocked("Collection stopped; failed and unexecuted observations are preserved")
        return
    import httpx
    access_token = os.environ[arguments.token_env]
    async with httpx.AsyncClient(timeout=control.settings.timeout_seconds, follow_redirects=False, trust_env=False) as client:
        await collect_cases(cases=cases, dataset=arguments.dataset, output=arguments.output_dir, control=control, runtime=runtime, client=client, access_token=access_token)
    if control.stopped:
        raise ExecutionBlocked("Collection stopped; failed and unexecuted observations are preserved")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--runtime-record", type=Path, required=True)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--token-env", default="TRAVELMATE_EVAL_ACCESS_TOKEN")
    parser.add_argument("--output-dir", type=Path, required=True)
    asyncio.run(collect(parser.parse_args()))


if __name__ == "__main__":
    main()
