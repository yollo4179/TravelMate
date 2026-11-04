"""One bounded runner for module comparisons on a separate evaluation server."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
import os
from pathlib import Path
import uuid
from typing import Any

from common.dataset.io import canonical_digest, digest, read_json, write_json, write_jsonl
from common.execution.control import AttemptStatus, ExecutionBlocked, Operation, RunControl, RunMode
from common.experiments.contracts import ExperimentConfig, ModuleContext, ModuleInput, ModuleKind, ModuleRegistry
from common.experiments.modules import DEFAULT_MODULES
from common.paths import EVALUATION_ROOT
from common.runs.run_record import evaluator_git_sha
from tracks.search.collect_live import latency_summary, selected_v14_inputs
from tracks.search.score_ranking import score_search_api_record


def prepare(config: ExperimentConfig, registry: ModuleRegistry) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if digest(config.dataset / "manifest.json") != config.dataset_manifest_sha256 or digest(config.runtime_record) != config.runtime_sha256:
        raise ExecutionBlocked("Frozen dataset or runtime record changed after configuration")
    cases = selected_v14_inputs(config.dataset, config.execution.case_ids)
    runtime = read_json(config.runtime_record)
    if runtime.get("environment") != "evaluation" or runtime.get("server_url") != config.server_url:
        raise ExecutionBlocked("Explicit evaluation-server binding required; do not target the production server")
    profile = config.variants[0].backend_profile
    if runtime.get("backend_profile") != profile:
        raise ExecutionBlocked("Selected modules/model/prompt differ from the recorded active backend profile")
    if runtime.get("corpus_sha256") != digest(config.dataset / "generated/corpus.json"):
        raise ExecutionBlocked("The runtime record must refer to the selected frozen corpus")
    if config.execution.mode == RunMode.LIVE and runtime.get("execution_mode") != "LIVE":
        raise ExecutionBlocked("A mock runtime cannot stand for a LIVE evaluation server")
    operations = {ModuleKind.SEARCH_API: Operation.SEARCH, ModuleKind.CONVERSATION_API: Operation.CONVERSATION}
    counts = Counter(operations[item.kind] for item in config.variants)
    for operation, per_case in counts.items():
        config.execution.require_capacity(operation, per_case * len(cases))
    # Validate every projection and module match BEFORE the first external request.
    for variant in config.variants:
        module = registry.select(variant.kind)
        for case in cases:
            module.request(ModuleInput(case=case, input_sha256=case["input_sha256"],
                                       conversation_id="preview", turn_key="preview"), variant, config.server_url)
    return cases, runtime


def mock_responses(config: ExperimentConfig, planned: list[tuple[Any, ModuleInput, Any, dict[str, Any]]]) -> dict[str, dict[str, Any]]:
    if config.fixtures is None:
        return {}
    fixtures = read_json(config.fixtures)
    expected = {variant.identifier + ":" + supplied.case["case_id"] for variant, supplied, _, _ in planned}
    if set(fixtures) != expected:
        raise ValueError("MOCK fixtures must cover exactly the selected variant/case pairs")
    responses = {}
    for variant, supplied, _, request in planned:
        fixture = fixtures[variant.identifier + ":" + supplied.case["case_id"]]
        if fixture.get("input_sha256") != supplied.input_sha256 or fixture.get("body_sha256") != request["body_sha256"]:
            raise ValueError("MOCK fixture input or original request body hash mismatch")
        if not isinstance(fixture.get("response"), dict):
            raise ValueError("MOCK fixture must contain an explicit HTTP response object")
        key = canonical_digest(request)
        if key in responses and responses[key]["response"] != fixture["response"]:
            raise ValueError("Identical requests cannot have conflicting fixtures")
        responses[key] = {"response": fixture["response"]}
    return responses


async def run_experiment(
    config: ExperimentConfig,
    output: Path,
    *,
    execute_live: bool = False,
    registry: ModuleRegistry = DEFAULT_MODULES,
) -> dict[str, Any]:
    if config.execution.mode == RunMode.LIVE and not execute_live:
        raise ExecutionBlocked("LIVE is never implicit; pass --execute-live for the explicitly configured scope")
    cases, runtime = prepare(config, registry)
    target = output.resolve()
    if target.is_relative_to(config.dataset) or target.is_relative_to(EVALUATION_ROOT / "datasets"):
        raise ValueError("Results cannot be written into frozen datasets")
    run_id = str(uuid.uuid4())
    planned = []
    for variant in config.variants:
        module = registry.select(variant.kind)
        for case in cases:
            # Fresh identities on each run; restarting does not reuse an old server receipt.
            supplied = ModuleInput(case=case, input_sha256=case["input_sha256"],
                                   conversation_id=str(uuid.uuid4()), turn_key=str(uuid.uuid4()))
            planned.append((variant, supplied, module, module.request(supplied, variant, config.server_url)))
    fixtures = mock_responses(config, planned)
    access_token = None
    if config.execution.mode == RunMode.LIVE:
        access_token = os.environ[config.token_env]
        if not access_token.strip():
            raise ValueError("The explicitly named evaluation access token is empty")
    # The one output directory contains evidence only; no server/JAR/settings tree is copied.
    target.mkdir(parents=True, exist_ok=False)
    control = RunControl(config.execution, target / "attempts.jsonl", mock_responses=fixtures)
    context = ModuleContext(server_url=config.server_url, runtime=runtime, control=control, access_token=access_token)
    records: dict[str, list[dict[str, Any]]] = {variant.identifier: [] for variant in config.variants}
    scores: dict[str, list[dict[str, Any]]] = {variant.identifier: [] for variant in config.variants}
    manifest = {"schema_version": "module-experiment-run-v1", "run_id": run_id,
                "evaluator_git_sha": evaluator_git_sha(), "configuration_sha256": config.configuration_sha256,
                "runtime_record_sha256": config.runtime_sha256, "runtime_record": str(config.runtime_record),
                "dataset_manifest_sha256": digest(config.dataset / "manifest.json"),
                "execution_mode": config.execution.mode.value, "variants": [asdict(item) for item in config.variants],
                "selected_inputs": [{"case_id": case["case_id"], "input_sha256": case["input_sha256"], "original_input": case["input"]} for case in cases],
                "status": "started", "internal_provider_call_counts": None,
                "input_count_cost_usd": None, "total_billed_cost_usd": None}
    write_json(target / "run.json", manifest)
    write_jsonl(target / "requests.jsonl", [{"variant": variant.identifier, "case_id": supplied.case["case_id"],
                                           "input_sha256": supplied.input_sha256, "request": request}
                                          for variant, supplied, _, request in planned])
    completed: set[str] = set()
    failure: str | None = None

    async def execute() -> None:
        for variant, supplied, module, _ in planned:
            record = await module.execute(supplied, variant, context)
            records[variant.identifier].append(record)
            completed.add(variant.identifier + ":" + supplied.case["case_id"])
            write_jsonl(target / variant.identifier / "records.jsonl", records[variant.identifier])
            if variant.kind == ModuleKind.SEARCH_API:
                score = score_search_api_record(supplied.case, record)
                scores[variant.identifier].append({"case_id": supplied.case["case_id"], **score})
                write_jsonl(target / variant.identifier / "scores.jsonl", scores[variant.identifier])
            if control.stopped or record["execution_status"] != AttemptStatus.COMPLETED:
                raise ExecutionBlocked("Stopped on first failed module result; no retry or later variant")

    try:
        if config.execution.mode == RunMode.MOCK:
            await execute()
        else:
            import httpx
            # HTTPX's default transport has zero retries and preserves proxy/CA environment settings.
            async with httpx.AsyncClient(timeout=config.execution.timeout_seconds, follow_redirects=False) as client:
                context.client = client
                await execute()
    except BaseException as exception:
        failure = type(exception).__name__
        control.stopped = True
        if not isinstance(exception, Exception):
            raise
    finally:
        summary = {
            "status": "failed" if failure else "completed", "failure_type": failure,
            "quality_status": "mock_regression_only" if config.execution.mode == RunMode.MOCK else "requires_track_assessment",
            "execution": control.summary(), "not_run": [variant.identifier + ":" + supplied.case["case_id"]
                                                       for variant, supplied, _, _ in planned
                                                       if variant.identifier + ":" + supplied.case["case_id"] not in completed],
            "by_variant": {variant.identifier: {"records": len(records[variant.identifier]),
                           "latency": latency_summary(records[variant.identifier])} for variant in config.variants},
            "internal_provider_call_counts": None, "internal_search_call_counts": None,
            "input_count_cost_usd": None, "total_billed_cost_usd": None,
        }
        write_json(target / "summary.json", summary)
        write_json(target / "run.json", {**manifest, "status": summary["status"]})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    arguments = parser.parse_args()
    config = ExperimentConfig.load(arguments.config)
    if arguments.preview:
        cases, _ = prepare(config, DEFAULT_MODULES)
        print(f"Validated {len(cases)} cases x {len(config.variants)} variants; no journal, client or HTTP created")
        return
    if arguments.output_dir is None:
        parser.error("--output-dir is required for a new evidence-only run")
    summary = asyncio.run(run_experiment(config, arguments.output_dir, execute_live=arguments.execute_live))
    print(f"{summary['status']}: {arguments.output_dir}")
    raise SystemExit(0 if summary["status"] == "completed" else 1)
