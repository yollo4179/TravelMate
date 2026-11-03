"""One-shot supervisor and raw HTTP recorder for the approved two existing cases."""
from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any
import uuid

import httpx

ROOT = Path("C:/ssafy/Travelmate")
SOURCE = ROOT / ".local-backups/search-category-retest-build"
RUNTIME = ROOT / ".local-backups/openai-strict-live-20261103-04"
RESULTS = RUNTIME / "results"
MODEL = "gpt-5.4-mini-2026-03-17"
API_UPSTREAM = "https://api.openai.com"
COUNTERS = {"/v1/responses/input_tokens": 0, "/v1/responses": 0}
LOCK = threading.Lock()
HALTED = threading.Event()


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_events() -> list[dict[str, Any]]:
    path = RUNTIME / "observations/execution.jsonl"
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()] if path.exists() else []


def schema_comparison_value(schema: Any) -> Any:
    if isinstance(schema, dict):
        return {
            name: sorted(value) if name == "required" and isinstance(value, list)
                    and all(isinstance(field, str) for field in value) else schema_comparison_value(value)
            for name, value in schema.items()
        }
    if isinstance(schema, list):
        return [schema_comparison_value(item) for item in schema]
    return schema


class Recorder(BaseHTTPRequestHandler):
    def log_message(self, format: str, *arguments: Any) -> None:
        return

    def read_request_body(self) -> bytes:
        if self.headers.get("Transfer-Encoding", "").lower() != "chunked":
            return self.rfile.read(int(self.headers.get("Content-Length", "0")))
        chunks: list[bytes] = []
        while True:
            chunk_size = int(self.rfile.readline().split(b";", 1)[0].strip(), 16)
            if chunk_size == 0:
                while self.rfile.readline() != b"\r\n":
                    pass
                return b"".join(chunks)
            chunk = self.rfile.read(chunk_size)
            if len(chunk) != chunk_size or self.rfile.read(2) != b"\r\n":
                raise ValueError("Incomplete chunked request body")
            chunks.append(chunk)

    def do_POST(self) -> None:
        raw_request = self.read_request_body()
        with LOCK:
            if HALTED.is_set() or self.path not in COUNTERS or COUNTERS[self.path] >= 4:
                self.send_error(429, "Approved one-shot request cap or stop policy reached")
                HALTED.set()
                return
            (RESULTS / f"received-{sum(COUNTERS.values()) + 1:02d}.request.json").write_bytes(raw_request)
            parsed = json.loads(raw_request)
            expected_schema = json.loads((RUNTIME / "provider-schema.expected.json").read_text(encoding="utf-8"))
            actual_tools = parsed.get("tools", [])
            if len(actual_tools) != 1 or schema_comparison_value(actual_tools[0].get("parameters")) != schema_comparison_value(expected_schema) or actual_tools[0].get("strict") is not True:
                HALTED.set()
                self.send_error(400, "Deployed strict category schema does not match verified build")
                return
            if parsed.get("model") != MODEL or any(tool.get("name") != "search_places" for tool in parsed.get("tools", [])):
                self.send_error(400, "Request outside approved model/tool scope")
                HALTED.set()
                return
            COUNTERS[self.path] += 1
            ordinal = sum(COUNTERS.values())
            kind = "count" if self.path.endswith("input_tokens") else "inference"
            prefix = f"{ordinal:02d}-{kind}"
            (RESULTS / f"{prefix}.request.json").write_bytes(raw_request)
            write_json(RESULTS / "provider-attempts.json", {"counts": COUNTERS, "started_at": datetime.now(UTC).isoformat()})
        started = time.perf_counter()
        metadata: dict[str, Any] = {"kind": kind, "route": self.path, "model": MODEL, "request_transfer_encoding": self.headers.get("Transfer-Encoding"), "request_content_length": self.headers.get("Content-Length")}
        try:
            with httpx.Client(timeout=httpx.Timeout(240, connect=10), transport=httpx.HTTPTransport(retries=0), trust_env=False) as client:
                response = client.post(API_UPSTREAM + self.path,
                        headers={"Authorization": self.headers.get("Authorization", ""), "Content-Type": "application/json"},
                        content=raw_request)
            (RESULTS / f"{prefix}.response.json").write_bytes(response.content)
            metadata.update(http_status=response.status_code, provider_request_id=response.headers.get("x-request-id"),
                    duration_ms=(time.perf_counter() - started) * 1000)
            write_json(RESULTS / f"{prefix}.metadata.json", metadata)
            if response.status_code >= 400:
                HALTED.set()
            self.send_response(response.status_code)
            self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
            self.send_header("Content-Length", str(len(response.content)))
            self.end_headers()
            self.wfile.write(response.content)
        except Exception as exception:
            HALTED.set()
            metadata.update(error_type=type(exception).__name__, outcome="UNKNOWN_NO_RETRY",
                    duration_ms=(time.perf_counter() - started) * 1000)
            write_json(RESULTS / f"{prefix}.metadata.json", metadata)
            self.send_error(502, "Provider transport failed; no retry")


def main() -> None:
    scope = json.loads((RUNTIME / "execution-scope.json").read_text(encoding="utf-8"))
    cases = scope["case_requests"]
    assert [case["case_id"] for case in cases] == ["PLR-TM-palaces-01", "PLR-TM-palaces-03"]
    assert not read_events() and not (RUNTIME / "inference-reservations.jsonl").exists()
    with (RESULTS / "started.json").open("x", encoding="utf-8") as receipt:
        json.dump({"started_at": datetime.now(UTC).isoformat(), "model": MODEL, "retries": 0}, receipt)
    helper_path = SOURCE / "Evaluation/environments/b-plan/run_b.py"
    sys.path.insert(0, str(helper_path.parent))
    specification = importlib.util.spec_from_file_location("frozen_b_collector", helper_path)
    assert specification and specification.loader
    helper = importlib.util.module_from_spec(specification)
    sys.modules[specification.name] = helper
    specification.loader.exec_module(helper)
    token = helper.access_token(json.loads((RUNTIME / "private.json").read_text(encoding="utf-8"))["jwt_secret"])
    proxy = ThreadingHTTPServer(("127.0.0.1", 18082), Recorder)
    thread = threading.Thread(target=proxy.serve_forever, daemon=True)
    thread.start()
    bindings: list[dict[str, Any]] = []
    outcomes: list[dict[str, Any]] = []
    failure = None
    try:
        with httpx.Client(timeout=httpx.Timeout(700, connect=10), transport=httpx.HTTPTransport(retries=0), trust_env=False) as client:
            for case in cases:
                if HALTED.is_set() or COUNTERS["/v1/responses"] + 2 > 4 or COUNTERS["/v1/responses/input_tokens"] + 2 > 4:
                    raise RuntimeError("Batch halted or insufficient remaining request allowance")
                case_id = case["case_id"]
                turn_id = str(uuid.uuid4())
                headers = {"Authorization": "Bearer " + token, "Idempotency-Key": turn_id,
                        "X-Conversation-Id": str(uuid.uuid4()), "X-Evaluation-Case-Id": case_id,
                        "X-Evaluation-Input-Sha256": case["input_sha256"]}
                write_json(RESULTS / f"{case_id}.request.json", {**case, "turn_id": turn_id, "mode": "LIVE"})
                started = time.perf_counter()
                response = client.post("http://127.0.0.1:18080/api/v1/conversation/turns", headers=headers, json=case["api_request"])
                (RESULTS / f"{case_id}.response.json").write_bytes(response.content)
                native = response.json()
                outcome = {"case_id": case_id, "http_status": response.status_code,
                        "duration_ms": (time.perf_counter() - started) * 1000,
                        "request_id": response.headers.get("X-Request-Id"), "termination": native.get("termination"),
                        "type": native.get("type"), "model_turns": native.get("modelTurns")}
                outcomes.append(outcome)
                write_json(RESULTS / f"{case_id}.metadata.json", outcome)
                bindings.append({"case_id": case_id, "input_sha256": case["input_sha256"], "request_id": outcome["request_id"],
                        "api_request": case["api_request"]})
                write_json(RESULTS / "bindings.json", bindings)
                response.raise_for_status()
                if native.get("termination") != "COMPLETED" or native.get("type") != "PLACES":
                    raise RuntimeError("First execution error: " + str(native.get("termination")))
                results = native.get("toolResults", [])
                if len(results) != 1 or results[0].get("name") != "search_places" or results[0].get("status") != "SUCCEEDED":
                    raise RuntimeError("Unexpected or failed search tool result")
                if sum(event["event"] == "TOOL_RESULT" for event in read_events()) > 2:
                    raise RuntimeError("Search tool cap exceeded")
    except Exception as exception:
        HALTED.set()
        failure = {"type": type(exception).__name__, "message": str(exception)}
    finally:
        proxy.shutdown()
        proxy.server_close()
        events = read_events()
        source_events = RUNTIME / "observations/execution.jsonl"
        if source_events.exists():
            (RESULTS / "execution.jsonl").write_bytes(source_events.read_bytes())
        usage_rows: list[dict[str, Any]] = []
        for path in sorted(RESULTS.glob("*-inference.response.json")):
            observed = json.loads(path.read_text(encoding="utf-8"))
            usage = observed.get("usage")
            row: dict[str, Any] = {"file": path.name, "model": observed.get("model"), "status": observed.get("status"), "usage": usage}
            if usage and isinstance(usage.get("input_tokens"), int) and isinstance(usage.get("output_tokens"), int):
                input_tokens, output_tokens = usage["input_tokens"], usage["output_tokens"]
                cached = usage.get("input_tokens_details", {}).get("cached_tokens", 0)
                row["inference_cost_without_cache_discount_usd"] = str((Decimal(input_tokens) * Decimal('0.75') + Decimal(output_tokens) * Decimal('4.50')) / 1000000)
                row["usage_based_inference_cost_usd"] = str((Decimal(input_tokens - cached) * Decimal('0.75') + Decimal(cached) * Decimal('0.075') + Decimal(output_tokens) * Decimal('4.50')) / 1000000)
            else:
                row["usage_based_inference_cost_usd"] = None
            usage_rows.append(row)
        trace_metadata = json.loads((RUNTIME / "trace-source.json").read_text(encoding="utf-8"))
        trace = Path(trace_metadata["path"])
        if trace.exists():
            with trace.open("rb") as trace_source:
                trace_source.seek(trace_metadata["offset"])
                (RESULTS / "search-traces.jsonl").write_bytes(trace_source.read())
        report = {"state": "STOPPED_ON_FIRST_ERROR" if failure else "COMPLETED_RECORDED_NOT_JUDGED", "failure": failure,
                "model": MODEL, "case_results": outcomes,
                "not_run_cases": [case["case_id"] for case in cases if case["case_id"] not in {row["case_id"] for row in outcomes}],
                "inference_attempts": COUNTERS["/v1/responses"], "input_count_attempts": COUNTERS["/v1/responses/input_tokens"],
                "search_tool_attempts": sum(event["event"] == "TOOL_RESULT" for event in events),
                "usage_rows": usage_rows, "input_count_cost_usd": None, "total_billed_cost_usd": None,
                "total_cost_bound_usd": None, "inference_cost_limit_usd": "0.047616", "invoice_confirmed": False,
                "retries": 0, "plan_calls": 0, "judge_calls": 0, "finished_at": datetime.now(UTC).isoformat()}
        write_json(RESULTS / "run.json", report)
        print(json.dumps({key: value for key, value in report.items() if key != "usage_rows"}, ensure_ascii=True), flush=True)


if __name__ == "__main__":
    main()
