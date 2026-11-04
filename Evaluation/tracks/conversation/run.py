"""Collect the current server path and score tools, response text and original citations."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import AsyncExitStack
import json
import os
from pathlib import Path
import sys
import uuid
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import canonical_digest, digest, read_json, read_jsonl, write_json, write_jsonl
from common.execution.control import ExecutionBlocked, ExecutionSettings, Operation, RunControl, RunMode
from common.experiments.contracts import ModuleConfig, ModuleContext, ModuleInput, ModuleKind
from common.experiments.modules import DEFAULT_MODULES
from common.paths import EVALUATION_ROOT
from common.runs.run_record import evaluator_git_sha
from tracks.conversation.cases import DEFAULT_SUITE, load_cases
from tracks.conversation.review import export_review, summarize
from tracks.conversation.score import score_case
from tracks.conversation.log_types import TestLogPath, EvaluationStage
from tracks.conversation.test_logs import TestLogs


def prepared_cases(arguments: argparse.Namespace, settings: ExecutionSettings) -> list[dict[str, Any]]:
    if digest(arguments.suite) != settings.parameter("suite_sha256"):
        raise ValueError("Conversation suite differs from the approved configuration")
    bindings = read_json(arguments.bindings) if arguments.bindings is not None else {}
    if canonical_digest(bindings) != settings.parameter("bindings_sha256"):
        raise ValueError("Runtime bindings differ from the explicit configuration")
    cases = load_cases(arguments.suite, settings.case_ids, bindings)
    settings.require_capacity(Operation.RUNTIME_READ, 2)
    settings.require_capacity(Operation.CONVERSATION, len(cases))
    if settings.mode == RunMode.LIVE and any(case["creates_plan"] for case in cases) and settings.parameter("allow_plan_creation") is not True:
        raise ExecutionBlocked("Selected case creates a real planning job; explicit allow_plan_creation is required")
    return cases


def validate_contract(contract: dict[str, Any], cases: list[dict[str, Any]], settings: ExecutionSettings) -> None:
    if contract.get("schema_version") != "conversation-evaluation-contract-v1" or contract.get("environment") != "evaluation":
        raise ExecutionBlocked("The target is not the evaluation-profile conversation contract endpoint")
    if contract.get("evaluation_user", {}).get("user_id") != settings.parameter("expected_user_id"):
        raise ExecutionBlocked("Authenticated test account differs from the explicitly selected test user")
    tools = {tool["name"]: tool for tool in contract["tools"]}
    if len(tools) != len(contract["tools"]):
        raise ExecutionBlocked("Duplicate tool schemas in the actual server contract")
    for case in cases:
        expected = case["expected"]
        if any(name not in tools or tools[name]["tool_type"] != kind for name, kind in zip(expected["tool_names"], expected["tool_types"], strict=True)):
            raise ExecutionBlocked("The actual server does not provide an expected tool/type")
    minimum = 1 + max(len(case["expected"]["tool_names"]) for case in cases)
    # Limits are shared with the operating profile; the experiment must declare the values it measures.
    if contract["max_model_turns"] != settings.parameter("max_model_turns") or contract["max_tool_calls"] != settings.parameter("max_tool_calls"):
        raise ExecutionBlocked("Server conversation limits differ from the experiment configuration")
    if contract["max_tool_calls"] < minimum:
        raise ExecutionBlocked("Tool-call limit cannot cover pre-retrieval plus the expected tools")
    if contract["provider"] != settings.parameter("expected_provider") or contract["model"] != settings.parameter("expected_model"):
        raise ExecutionBlocked("Actual server provider/model differs from the explicit configuration")
    if settings.mode == RunMode.LIVE:
        from common.experiments.source_identity import source_identity
        if contract.get("source_sha256") != source_identity(EVALUATION_ROOT.parent / "Server/TravelMate/src/main"):
            raise ExecutionBlocked("Running Spring source differs from this checkout; rebuild the shared source")
        if contract.get("reasoning_mode") not in {"DISABLED", "UNSUPPORTED"}:
            raise ExecutionBlocked("Reasoning must be disabled for this evaluation")
        if contract.get("evaluation_budget_requirement") != "REQUIRED":
            raise ExecutionBlocked("Evaluation batch authorization must remain required")
        if contract.get("tool_contract_mode") != "STRICT_TOOLS_V1":
            raise ExecutionBlocked("Use the shared strict contract for all registered tools")
    if contract["provider"] == "OPENAI" and contract.get("response_format") != "JSON_SCHEMA_V1":
        raise ExecutionBlocked("The selected OpenAI evaluation server must enforce the conversation JSON schema")


async def collect(arguments: argparse.Namespace) -> dict[str, Any]:
    settings = ExecutionSettings.load(arguments.config)
    cases = prepared_cases(arguments, settings)
    server_url = settings.parameter("server_url").rstrip("/")
    from urllib.parse import urlsplit
    origin = urlsplit(server_url)
    if origin.scheme not in {"http", "https"} or not origin.hostname or origin.username or origin.password or origin.query or origin.fragment or origin.path not in {"", "/"}:
        raise ValueError("An explicit credential-free evaluation server origin is required")
    if (settings.mode == RunMode.MOCK) != (arguments.mock_responses is not None):
        raise ValueError("MOCK requires fixtures and LIVE forbids them")
    if settings.mode == RunMode.LIVE and not arguments.execute_live:
        raise ExecutionBlocked("LIVE requires --execute-live; preview and MOCK never imply approval")
    config = ModuleConfig(identifier="conversation", kind=ModuleKind.CONVERSATION_API, ranking_mode=None,
                          response_limit=None, expected_response_type=None, require_citations=False, backend_profile={})
    module = DEFAULT_MODULES.select(ModuleKind.CONVERSATION_API)
    fixture = read_json(arguments.mock_responses) if arguments.mock_responses is not None else None
    inputs = []
    for case in cases:
        identity = fixture["cases"][case["case_id"]]["identity"] if fixture is not None else {}
        supplied = ModuleInput(case=case, input_sha256=case["input_sha256"],
                               conversation_id=identity.get("conversation_id", str(uuid.uuid4())),
                               turn_key=identity.get("turn_id", str(uuid.uuid4())))
        request = module.request(supplied, config, server_url)
        inputs.append((supplied, request))
    request_contract = {"method": "GET", "url": server_url + "/api/evaluation/conversation-contract"}
    mock = {}
    if fixture is not None:
        mock[canonical_digest(request_contract)] = {"response": {"status_code": 200, "raw_body": json.dumps(fixture["contract"], ensure_ascii=False)}}
        for supplied, request in inputs:
            item = fixture["cases"][supplied.case["case_id"]]
            if item["input_sha256"] != supplied.input_sha256 or item["body_sha256"] != request["body_sha256"]:
                raise ValueError("MOCK fixture input/body hash mismatch")
            mock[canonical_digest(request)] = {"response": item["response"]}
    if fixture is not None:
        search_contract = {"method": "GET", "url": fixture["contract"]["search_endpoint"] + "/health"}
        mock[canonical_digest(search_contract)] = {"response": {"status_code": 200, "raw_body": json.dumps(fixture["search_contract"])}}
    output = arguments.output_dir.resolve()
    if output.is_relative_to(EVALUATION_ROOT / "datasets"):
        raise ValueError("Output must be outside all frozen datasets")
    output.mkdir(parents=True, exist_ok=False)
    control = TestLogs.write(output, TestLogPath.ATTEMPTS, {"settings": settings, "mock_responses": mock})
    from common.experiments.source_identity import evaluator_source_identity
    manifest = {"evaluator_git_sha": evaluator_git_sha(), "evaluator_source_sha256": evaluator_source_identity(EVALUATION_ROOT), "configuration_sha256": settings.configuration_sha256,
                "suite_sha256": digest(arguments.suite), "execution_mode": settings.mode.value,
                "selected_case_ids": list(settings.case_ids), "status": "started", "input_count_cost_usd": None,
                "total_billed_cost_usd": None}
    TestLogs.write(output, TestLogPath.RUN, manifest)
    TestLogs.write(output, TestLogPath.INPUTS, [{"case_id": item.case["case_id"], "input_sha256": item.input_sha256, "api_request": item.case["api_request"]} for item, _ in inputs])
    records = []
    scores = []
    captured_events = []
    contract = {}
    failure = None
    async with AsyncExitStack() as stack:
        client = None
        token = None
        try:
            if settings.mode == RunMode.LIVE:
                import httpx
                token = os.environ[settings.parameter("token_env")]
                client = await stack.enter_async_context(httpx.AsyncClient(timeout=settings.timeout_seconds, follow_redirects=False))
            async def metadata() -> dict[str, Any]:
                response = await client.get(request_contract["url"], headers={"Authorization": "Bearer " + token})
                return {"status_code": response.status_code, "raw_body": response.text}
            metadata_response = await control.execute(Operation.RUNTIME_READ, cases[0]["case_id"], request_contract, metadata)
            if metadata_response["status_code"] != 200:
                raise ExecutionBlocked("Evaluation contract endpoint rejected the request")
            contract = json.loads(metadata_response["raw_body"])
            TestLogs.write(output, TestLogPath.SERVER_CONTRACT, contract)
            validate_contract(contract, cases, settings)
            search_url = contract["search_endpoint"].rstrip("/")
            parsed_search = urlsplit(search_url)
            if parsed_search.scheme not in {"http", "https"} or not parsed_search.hostname or parsed_search.username or parsed_search.password or parsed_search.query or parsed_search.fragment:
                raise ExecutionBlocked("Search endpoint must be an explicit credential-free URL")
            search_request = {"method": "GET", "url": search_url + "/health"}
            async def search_metadata() -> dict[str, Any]:
                response = await client.get(search_request["url"])
                return {"status_code": response.status_code, "raw_body": response.text}
            search_response = await control.execute(Operation.RUNTIME_READ, cases[0]["case_id"], search_request, search_metadata)
            health = json.loads(search_response["raw_body"])
            from common.experiments.source_identity import search_source_identity
            if search_response["status_code"] != 200 or health.get("status") != "ok":
                raise ExecutionBlocked("Evaluation search server is not ready")
            if settings.mode == RunMode.LIVE and health.get("source_sha256") != search_source_identity(EVALUATION_ROOT.parent / "embedding-server"):
                raise ExecutionBlocked("Running embedding/reranking source differs from this checkout")
            TestLogs.write(output, TestLogPath.SEARCH_CONTRACT, health)
            if settings.mode == RunMode.LIVE:
                expected_devices = settings.parameter("expected_search_devices")
                if set(expected_devices) != {"embedding_device", "reranker_device"} or any(
                        str(health.get(name, "")).split(":")[0] != value for name, value in expected_devices.items()):
                    raise ExecutionBlocked("Actual embedding/reranker devices differ from the selected evaluation configuration")
            context = ModuleContext(server_url=server_url, runtime=contract, control=control, client=client, access_token=token)
            event_path = arguments.events or (Path(contract["observation_file"]) if contract.get("observation_file") else None)
            if settings.mode == RunMode.LIVE and (event_path is None or not event_path.is_absolute()):
                raise ExecutionBlocked("Run beside the test server with its accessible absolute --events path before paid calls")
            for supplied, _ in inputs:
                record = await module.execute(supplied, config, context)
                records.append(record)
                TestLogs.write(output, TestLogPath.RECORDS, records)
                if fixture is not None:
                    captured_events.extend(fixture["cases"][supplied.case["case_id"]]["events"])
                elif event_path is not None and event_path.is_file():
                    ids = {(item.get("native_response") or {}).get("requestId") for item in records if isinstance(item.get("native_response"), dict)}
                    captured_events = [event for event in read_jsonl(event_path) if event.get("requestId") in ids]
                if control.stopped or record["execution_status"] != "completed":
                    raise ExecutionBlocked("First application failure or unmet response contract; later cases not run")
                scored = score_case(supplied.case, record, captured_events, contract)
                if scored["automated_status"] != "passed":
                    raise ExecutionBlocked("First failed or unobserved tool/answer/evidence check; later cases not run")
        except BaseException as exception:
            failure = {"type": type(exception).__name__, "detail": str(exception)}
            control.stopped = True
            if not isinstance(exception, Exception):
                raise
        finally:
            if fixture is None and records:
                event_path = arguments.events or (Path(contract["observation_file"]) if contract.get("observation_file") else None)
                if event_path is not None and event_path.is_file():
                    ids = {(record.get("native_response") or {}).get("requestId") for record in records if isinstance(record.get("native_response"), dict)}
                    captured_events = [event for event in read_jsonl(event_path) if event.get("requestId") in ids]
            TestLogs.write(output, TestLogPath.EVENTS, captured_events)
            indexed = {case["case_id"]: case for case in cases}
            for record in records:
                scores.append(score_case(indexed[record["case_id"]], record, captured_events, contract))
            summary = {**summarize(scores, expected_count=len(cases)), "execution": control.summary(), "failure": failure,
                       "status": "failed" if failure else "collected", "not_run": [case["case_id"] for case in cases if not any(record["case_id"] == case["case_id"] for record in records)],
                       "stages": {stage.value: {
                           "selected": sum(case["evaluation_stage"] == stage.value for case in cases),
                           "recorded": sum(indexed[score["case_id"]]["evaluation_stage"] == stage.value for score in scores),
                           "plan_drafts_observed": sum(indexed[score["case_id"]]["evaluation_stage"] == stage.value and score["plan_content"]["status"] not in {"not_ready", "not_applicable"} for score in scores),
                           "quality_passed": sum(indexed[score["case_id"]]["evaluation_stage"] == stage.value and (stage != EvaluationStage.PLAN or score["plan_content"]["status"] == "passed") and score["quality_observed"] and score["semantic_status"] == "passed" and score["automated_status"] == "passed" for score in scores)
                       } for stage in EvaluationStage},
                       "internal_inference_call_total": None, "input_count_cost_usd": None, "total_billed_cost_usd": None}
            TestLogs.write(output, TestLogPath.REVIEW, scores)
            TestLogs.write(output, TestLogPath.SCORES, scores)
            TestLogs.write(output, TestLogPath.SUMMARY, summary)
            TestLogs.write(output, TestLogPath.RUN, {**manifest, "status": summary["status"]})
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", type=Path, default=DEFAULT_SUITE)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--bindings", type=Path)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--events", type=Path)
    parser.add_argument("--preview", action="store_true")
    parser.add_argument("--execute-live", action="store_true")
    arguments = parser.parse_args()
    if arguments.preview:
        settings = ExecutionSettings.load(arguments.config)
        cases = prepared_cases(arguments, settings)
        print(json.dumps({"case_input_hashes": {case["case_id"]: case["input_sha256"] for case in cases},
                          "native_requests": {case["case_id"]: case["api_request"] for case in cases},
                          "minimum_tool_cap": 1 + max(len(case["expected"]["tool_names"]) for case in cases),
                          "external_calls": 0}, ensure_ascii=False, indent=2))
        return
    if arguments.output_dir is None:
        parser.error("A new --output-dir is required")
    result = asyncio.run(collect(arguments))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["status"] == "collected" else 1)


if __name__ == "__main__":
    main()
