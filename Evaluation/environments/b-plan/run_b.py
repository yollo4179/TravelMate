"""Fixed B-plan collector. Default is offline inspection; --execute is explicit."""
from __future__ import annotations

import argparse
import asyncio
import base64
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import hmac
import json
from pathlib import Path
import sys
import time
from typing import Any
import uuid

import httpx

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT / "Evaluation"), str(Path(__file__).resolve().parent)]
from common.dataset.io import export_inputs, read_json, read_jsonl, write_jsonl
from tracks.tool_call.convert_server_trace import RecordMode, convert_records
import prepare

CASE_IDS = ("PLR-TM-palaces-01", "PLR-TM-palaces-03", "PLR-TM-palaces-04", "PLR-TM-family_parks-04")
SCOPE = ROOT / "Evaluation/runs/contextual/runtime-qwen-independent-search-v1/20261102-01/execution-scope-proposal.json"
ENDPOINT = "http://127.0.0.1:18080/api/v1/conversation/turns"


class BatchProfile(StrEnum):
    ORIGINAL = "original-four"
    GPU_DIAGNOSTIC = "gpu-two"


def batch_scope(profile: BatchProfile) -> tuple[tuple[str, ...], list[dict[str, Any]], int, int]:
    scopes = {
        BatchProfile.ORIGINAL: (SCOPE, CASE_IDS, 8, 4),
        BatchProfile.GPU_DIAGNOSTIC: (
            ROOT / "Evaluation/runs/contextual/search-tool-contract-output-v1/20261102-01/next-execution-proposal.json",
            CASE_IDS[:2], 4, 2,
        ),
    }
    scope_path, case_ids, model_cap, search_cap = scopes[profile]
    requests = read_json(scope_path)["case_requests"]
    if tuple(row["case_id"] for row in requests) != case_ids or any(row["repeats"] != 1 for row in requests):
        raise ValueError("The approved fixed scope changed")
    return case_ids, requests, model_cap, search_cap


def observed_attempts(events: list[dict[str, Any]]) -> tuple[int, int]:
    model_calls = sum(event["event"] == "MODEL_CALL" and event["payload"].get("stage") == "FINISHED"
                      and event["payload"].get("dispatched") is True for event in events)
    tool_attempts = sum(event["event"] == "TOOL_RESULT" and event["payload"]["result"]["name"] == "search_places"
                        for event in events)
    return model_calls, tool_attempts


class RunStatus(StrEnum):
    STARTED = "STARTED"
    STOPPED = "STOPPED"
    RECORDED = "RECORDED_NOT_SCORED"


class ExecutionMode(StrEnum):
    INSPECT = "OFFLINE_INSPECTION"
    EXECUTE = "EXECUTE_REQUESTED"


def execution_blockers(runtime: Path) -> list[str]:
    snapshot = read_json(runtime / "snapshot.json")
    verified = read_json(runtime / "database-verification.json")
    evidence = read_json(runtime / "evidence-inventory.json")
    deployment_path = runtime / "original-fields/deployment.json"
    deployment = read_json(deployment_path) if deployment_path.exists() else snapshot
    jar_path = Path(deployment.get("jar_path", runtime / "spring.jar"))
    original_inventory = runtime / "original-fields/inventory.json"
    if original_inventory.exists():
        from prepare_original_fields import frozen_descriptions
        from app.contextual.original_fields import validate_description_evidence
        from app.enrichment.contracts import ExistingPlace
        fields = read_json(runtime / "original-fields/evidence.json")
        descriptions, binding = frozen_descriptions()
        expected = {place["id"]: ExistingPlace.from_mapping(place) for place in descriptions}
        for field in fields:
            validate_description_evidence(field, expected[field["metadata"]["place_id"]])
            if field["metadata"]["corpus_sha256"] != binding.corpus_sha256:
                raise ValueError("Original-field evidence uses another frozen corpus")
        if {field["metadata"]["place_id"] for field in fields} != set(expected):
            raise ValueError("Original-field evidence is incomplete")
        evidence = {"b_case_place_evidence": read_json(original_inventory)["place_evidence"]}
    blockers = []
    if not verified["spring_rows_match_snapshot"] or not verified["search_original_columns_match_snapshot"]:
        blockers.append("corpus_snapshot_mismatch")
    if verified["pending_search_jobs"] or verified["pending_spring_outbox"]:
        blockers.append("pending_jobs")
    if any(status not in (prepare.EvidenceStatus.READY, prepare.EvidenceStatus.FIELD_READY) for status in evidence["b_case_place_evidence"].values()):
        blockers.append("B_anchors_have_no_preserved_structured_evidence")
    if prepare.file_sha256(jar_path) != deployment["jar_sha256"]:
        blockers.append("jar_changed")
    if any(prepare.file_sha256(ROOT / path) != expected for path, expected in deployment["source_file_sha256"].items()):
        blockers.append("runtime_source_changed")
    settings = dict(line.split("=", 1) for line in (runtime / "spring.properties").read_text(encoding="utf-8").splitlines()
                    if line and not line.startswith("#"))
    expected = {"server.port": "18080", "llm.provider": "QWEN", "ollama.model": "qwen3:8b",
                "ollama.context-tokens": "8192", "ollama.max-output-tokens": "1536",
                "travelmate.conversation.allowed-tools": "SEARCH_PLACES",
                "travelmate.conversation.max-model-turns": "2", "travelmate.conversation.max-tool-calls": "1",
                "travelmate.conversation.tool-failure-policy": "STOP"}
    if any(settings.get(key) != value for key, value in expected.items()):
        blockers.append("server_caps_or_model_settings_mismatch")
    return blockers


def access_token(secret: str) -> str:
    def encode(payload: bytes) -> str:
        return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
    now = int(time.time())
    header = encode(b'{"alg":"HS512","typ":"JWT"}')
    claims = encode(json.dumps({"sub": prepare.EVALUATION_USER, "roles": "ROLE_BASE", "token_type": "access",
                               "iat": now, "exp": now + 3600}, separators=(",", ":")).encode())
    signing_input = f"{header}.{claims}"
    return signing_input + "." + encode(hmac.new(secret.encode(), signing_input.encode(), hashlib.sha512).digest())


def validate_completed_turn(response: dict[str, Any], events: list[dict[str, Any]]) -> tuple[int, int]:
    if response.get("termination") != "COMPLETED" or response.get("type") != "PLACES":
        raise ValueError("Unexpected or incomplete B search response; stop without retry")
    tool_results = response.get("toolResults", [])
    if len(tool_results) != 1 or tool_results[0].get("name") != "search_places" or tool_results[0].get("status") == "FAILED":
        raise ValueError("Expected exactly one successful search_places execution")
    turns = [event["payload"] for event in events if event["event"] == "MODEL_TURN"]
    calls = [call for turn in turns for call in turn["toolCalls"]]
    if len(calls) != 1 or calls[0]["name"] != "search_places":
        raise ValueError("Unexpected, repeated or missing tool selection")
    finished = [event["payload"] for event in events if event["event"] == "MODEL_CALL" and event["payload"].get("stage") == "FINISHED"]
    if len(finished) != 2 or any(call.get("status") != "SUCCEEDED" or not call.get("dispatched") for call in finished):
        raise ValueError("Missing or failed model-call observations")
    if any(call.get("provider") != "QWEN" or call.get("model") != "qwen3:8b" for call in finished):
        raise ValueError("Unexpected provider/model")
    return len(finished), len(tool_results)


async def execute(runtime: Path, output: Path, profile: BatchProfile = BatchProfile.ORIGINAL) -> None:
    case_ids, requests, model_cap, search_cap = batch_scope(profile)
    trace_path = runtime / "observations/execution.jsonl"
    if trace_path.exists() and trace_path.stat().st_size:
        raise ValueError("Runtime already contains request observations; do not repeat the batch")
    if output.exists():
        raise ValueError("Output exists; never overwrite/retry a batch")
    corpus = {place["id"]: place for place in read_json(ROOT / "Evaluation/datasets/v1.4.0/generated/corpus.json")}
    cases = [case for case in read_jsonl(ROOT / "Evaluation/datasets/v1.4.0/generated/golden.jsonl") if case["case_id"] in case_ids]
    exported = export_inputs(cases, corpus)
    by_case = {row["case_id"]: row for row in exported}
    if any(by_case[row["case_id"]]["input_sha256"] != row["input_sha256"] for row in requests):
        raise ValueError("Frozen case input hash mismatch")
    output.mkdir(parents=True)
    write_jsonl(output / "exported-inputs.jsonl", exported)
    bindings: list[dict[str, Any]] = []
    completed_model_calls = completed_search_calls = sent_requests = 0
    status = RunStatus.STARTED
    failure = None
    secret = read_json(runtime / "private.json")["jwt_secret"]
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(1800, connect=10), transport=httpx.AsyncHTTPTransport(retries=0), trust_env=False) as client:
            for case in requests:
                existing = read_jsonl(trace_path) if trace_path.exists() else []
                dispatched, search_attempts = observed_attempts(existing)
                if dispatched + 2 > model_cap or search_attempts + 1 > search_cap or sent_requests >= len(case_ids):
                    raise ValueError("Insufficient remaining batch budget; stop before next request")
                case_id = case["case_id"]
                turn_id = str(uuid.uuid4())
                headers = {"Authorization": "Bearer " + access_token(secret), "Idempotency-Key": turn_id,
                           "X-Conversation-Id": by_case[case_id]["model_input"]["conversationId"],
                           "X-Evaluation-Case-Id": case_id, "X-Evaluation-Input-Sha256": case["input_sha256"]}
                sent_requests += 1
                prepare.write_json(output / "attempt.json", {"sent_requests": sent_requests, "case_id": case_id, "turn_id": turn_id})
                prepare.write_json(output / f"{case_id}.request.json", {
                    "case_id": case_id, "input_sha256": case["input_sha256"], "turn_id": turn_id,
                    "conversation_id": by_case[case_id]["model_input"]["conversationId"],
                    "endpoint": ENDPOINT, "api_request": case["api_request"],
                })
                response = await client.post(ENDPOINT, headers=headers, json=case["api_request"])
                (output / f"{case_id}.response.json").write_text(response.text, encoding="utf-8")
                prepare.write_json(output / f"{case_id}.response-metadata.json", {
                    "http_status": response.status_code, "request_id": response.headers.get("X-Request-Id"),
                    "conversation_id": response.headers.get("X-Conversation-Id"),
                })
                response.raise_for_status()
                native = response.json()
                binding = {"case_id": case_id, "input_sha256": case["input_sha256"],
                           "request_id": response.headers["X-Request-Id"], "api_request": case["api_request"],
                           "runtime_verification": {"corpus_verified": True, "configuration_verified": False,
                                                    "corpus_sha256": read_json(runtime / "snapshot.json")["frozen_corpus_sha256"]}}
                bindings.append(binding)
                write_jsonl(output / "bindings.jsonl", bindings)
                events = read_jsonl(trace_path)
                selected = [event for event in events if event.get("requestId") == binding["request_id"]]
                model_count, search_count = validate_completed_turn(native, selected)
                completed_model_calls += model_count
                completed_search_calls += search_count
                if completed_model_calls > model_cap or completed_search_calls > search_cap or sent_requests > len(case_ids):
                    raise ValueError("Batch budget exceeded")
                records = convert_records(events, bindings, exported, mode=RecordMode.LIVE)
                write_jsonl(output / "records.jsonl", records)
        status = RunStatus.RECORDED
    except Exception as exception:
        status = RunStatus.STOPPED
        failure = f"{type(exception).__name__}: {exception}"
        raise
    finally:
        actual_models = actual_tools = 0
        if trace_path.exists():
            (output / "events.jsonl").write_bytes(trace_path.read_bytes())
            actual_models, actual_tools = observed_attempts(read_jsonl(trace_path))
        prepare.write_json(output / "run.json", {"status": status, "failure": failure, "created_at": datetime.now(UTC).isoformat(),
            "profile": profile, "case_ids": case_ids, "max_qwen_calls": model_cap, "max_search_calls": search_cap,
            "sent_requests": sent_requests, "completed_validated_model_calls": completed_model_calls,
            "completed_validated_search_calls": completed_search_calls, "retries": 0,
            "observed_dispatched_model_calls": actual_models, "observed_search_tool_attempts": actual_tools,
            "search_backend_dispatch_count_requires_database_audit": True,
            "actual_attempts_require_events_audit": True, "ranking_scores_comparable": False,
            "judge_calls": 0, "plan_jobs": 0})


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--runtime", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--profile", type=BatchProfile, choices=list(BatchProfile), default=BatchProfile.ORIGINAL)
    arguments = parser.parse_args()
    runtime = arguments.runtime.resolve()
    case_ids, _, model_cap, search_cap = batch_scope(arguments.profile)
    blockers = execution_blockers(runtime)
    print(json.dumps({"mode": ExecutionMode.EXECUTE if arguments.execute else ExecutionMode.INSPECT,
                      "case_ids": case_ids, "max_qwen_calls": model_cap, "max_search_calls": search_cap,
                      "blockers": blockers, "model_calls_made_by_inspection": 0}, ensure_ascii=False))
    if not arguments.execute:
        return
    if blockers:
        raise SystemExit("Live execution blocked before any API request")
    if arguments.output is None:
        parser.error("--execute requires a new --output directory")
    await execute(runtime, arguments.output.resolve(), arguments.profile)


if __name__ == "__main__":
    asyncio.run(main())
