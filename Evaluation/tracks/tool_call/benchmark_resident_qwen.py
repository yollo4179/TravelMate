"""Replay the same eight saved native requests twice without any API or inference call."""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import statistics
import subprocess
import sys
import time
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
PRIOR = ROOT / "Evaluation/runs/contextual/runtime-qwen-independent-search-v1/20261102-01"


def rows(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").split("\n") if line]


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def benchmark(profile: Path, output: Path) -> dict[str, Any]:
    if output.exists():
        raise FileExistsError("A previous measurement cannot be overwritten")
    saved = rows(PRIOR / "current-native-wires.jsonl")
    expected = rows(PRIOR / "runtime-counts.jsonl")
    if len(saved) != 8 or len(expected) != 8:
        raise ValueError("This replay is limited to the eight previously captured requests")
    show = json.loads((ROOT / "Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01/qwen-show.json").read_text(encoding="utf-8"))

    def envelope(wire: dict[str, Any]) -> dict[str, Any]:
        return {"wire": json.dumps(wire, ensure_ascii=False, separators=(",", ":")), "show": show,
                "version": {"version": "0.40.13"}, "tags": {"models": [{"name": "qwen3:8b",
                    "digest": "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"}]}}

    started = time.perf_counter()
    process = subprocess.Popen(
        [sys.executable, "-X", "utf8", str(ROOT / "Server/token_budget/exact_qwen_counter.py"), "--profile", str(profile), "--serve"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )
    transport = ThreadPoolExecutor(max_workers=1)

    def exchange(operation: str, request_id: str, wire: dict[str, Any]) -> dict[str, Any]:
        frame = {"operation": operation, "requestId": request_id, "payload": envelope(wire)}

        def send() -> dict[str, Any]:
            if process.stdin is None or process.stdout is None:
                raise RuntimeError("Missing worker transport")
            process.stdin.write(json.dumps(frame, ensure_ascii=False).encode("utf-8") + b"\n")
            process.stdin.flush()
            encoded = process.stdout.readline(65537)
            if not encoded.endswith(b"\n") or len(encoded) > 65536:
                raise ValueError("Missing or oversized worker response")
            return json.loads(encoded)

        result = transport.submit(send).result(timeout=90)
        if result.get("requestId") != request_id or result.get("status") != {"INIT": "READY", "COUNT": "COUNTED"}[operation]:
            raise ValueError("Worker request/status mismatch")
        return result

    measured = []
    try:
        ready = exchange("INIT", "initialize", saved[0]["wire"])
        startup_ms = (time.perf_counter() - started) * 1000
        session = ready["sessionId"]
        for iteration in range(2):
            for index, (captured, reference) in enumerate(zip(saved, expected, strict=True)):
                request_id = f"pass-{iteration + 1}-request-{index + 1}"
                request_started = time.perf_counter()
                response = exchange("COUNT", request_id, captured["wire"])
                elapsed_ms = (time.perf_counter() - request_started) * 1000
                count = response["payload"]
                for field in ("inputTokens", "wireSha256", "templateSha256", "promptSha256", "tokenIdsSha256"):
                    if count[field] != reference[field]:
                        raise ValueError("Resident output differs from the previously verified request: " + field)
                if response["sessionId"] != session or count["workerPid"] != ready["payload"]["workerPid"] or count["initializationCount"] != 1:
                    raise ValueError("Tokenizer process/session was recreated")
                measured.append({"case_id": captured["case_id"], "input_sha256": captured["input_sha256"],
                                 "scope": captured["scope"], "pass": iteration + 1, "request_id": request_id,
                                 "transport_and_calculation_ms": elapsed_ms, "count": count,
                                 "metadata_source": "SAVED_NOT_LIVE", "matches_previous_token_ids": True})
        if process.stdin is not None:
            process.stdin.close()
        if process.wait(timeout=10) != 0:
            raise RuntimeError("Worker failed during EOF shutdown")
    finally:
        if process.stdin is not None and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        transport.shutdown(wait=True, cancel_futures=True)
        if process.stdout is not None:
            process.stdout.close()
    output.mkdir(parents=True)
    write_json(output / "ready.json", ready)
    (output / "counts.jsonl").write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in measured), encoding="utf-8", newline="\n")
    durations = [row["transport_and_calculation_ms"] for row in measured]
    summary = {"baseline": "5f9e1238", "saved_requests": 8, "offline_passes": 2, "count_checks": len(measured),
               "initialization_count": 1, "unique_worker_pids": 1, "unique_session_ids": 1,
               "launcher_pid": process.pid, "worker_pid": ready["payload"]["workerPid"],
               "startup_wall_ms": startup_ms, "initialization_inside_worker_ms": ready["payload"]["initializationMs"],
               "repeat_calculation_transport_ms_min": min(durations), "repeat_calculation_transport_ms_median": statistics.median(durations),
               "repeat_calculation_transport_ms_max": max(durations),
               "worker_calculation_ms_median": statistics.median(row["count"]["calculationMs"] for row in measured),
               "all_previous_wire_prompt_token_id_hashes_match": True, "worker_exited_on_eof": True,
               "model_api_calls": 0, "search_calls": 0, "metadata_api_calls": 0, "production_changes": 0,
               "model_weights_inference": False, "server_reported_usage": None}
    write_json(output / "summary.json", summary)
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    print(json.dumps(benchmark(arguments.profile, arguments.output)))


if __name__ == "__main__":
    main()
