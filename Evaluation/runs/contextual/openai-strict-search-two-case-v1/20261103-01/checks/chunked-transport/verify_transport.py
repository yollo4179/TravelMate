"""Exercise the real Java client and recorder entirely through loopback fixtures."""
from __future__ import annotations

import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import json
from pathlib import Path
import subprocess
import threading

DIRECTORY = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("approved_transport", DIRECTORY.parent / "run-once.py")
assert SPEC and SPEC.loader
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)
recorder.RUNTIME = DIRECTORY
recorder.RESULTS = DIRECTORY / "transport"
recorder.RESULTS.mkdir()
recorder.API_UPSTREAM = "http://127.0.0.1:18083"
received: list[tuple[str, bytes]] = []


class Fixture(BaseHTTPRequestHandler):
    def log_message(self, format: str, *arguments: object) -> None:
        return

    def do_POST(self) -> None:
        body = self.rfile.read(int(self.headers["Content-Length"]))
        received.append((self.path, body))
        if self.path.endswith("input_tokens"):
            response = {"object": "response.input_tokens", "input_tokens": 1000}
        else:
            response = {"model": recorder.MODEL, "service_tier": "default", "status": "completed",
                        "output": [], "usage": {"input_tokens": 1, "output_tokens": 1}}
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


fixture = ThreadingHTTPServer(("127.0.0.1", 18083), Fixture)
proxy = ThreadingHTTPServer(("127.0.0.1", 18082), recorder.Recorder)
for server in (fixture, proxy):
    threading.Thread(target=server.serve_forever, daemon=True).start()
classpath = str(DIRECTORY / "classes") + ";" + str(DIRECTORY / "lib/*")
try:
    completed = subprocess.run(["java", "-cp", classpath, str(DIRECTORY / "TransportProbe.java"), str(DIRECTORY)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    (DIRECTORY / "java.stdout.log").write_text(completed.stdout, encoding="utf-8")
    (DIRECTORY / "java.stderr.log").write_text(completed.stderr, encoding="utf-8")
    assert completed.returncode == 0, "Real Java client offline transport failed; see preserved logs"
    assert len(received) == 4 and not recorder.HALTED.is_set()
    events = [json.loads(line) for line in (DIRECTORY / "events.jsonl").read_text(encoding="utf-8").splitlines()]
    finished = [event for event in events if event["event"] == "MODEL_CALL" and event["payload"]["stage"] == "FINISHED"]
    assert len(finished) == 2 and all(event["payload"]["status"] == "SUCCEEDED" for event in finished)
    cases = json.loads((DIRECTORY.parent / "execution-scope.json").read_text(encoding="utf-8"))["case_requests"]
    verification = []
    for index, (route, original) in enumerate(received, 1):
        kind = "count" if route.endswith("input_tokens") else "inference"
        recorded = recorder.RESULTS / f"{index:02d}-{kind}.request.json"
        assert recorded.read_bytes() == original
        metadata = json.loads((recorder.RESULTS / f"{index:02d}-{kind}.metadata.json").read_text(encoding="utf-8"))
        assert metadata["request_transfer_encoding"] == "chunked"
        parsed = json.loads(original)
        user = json.loads(parsed["input"][-1]["content"])
        assert user["message"] == cases[(index - 1) // 2]["api_request"]["message"]
        assert parsed["tools"][0]["strict"] is True
        if kind == "inference":
            assert hashlib.sha256(original).hexdigest() == finished[(index - 1) // 2]["payload"]["wireSha256"]
        verification.append({"route": route, "bytes": len(original), "sha256": hashlib.sha256(original).hexdigest(),
                             "upstream_bytes_equal_recorded_bytes": True, "request_transfer_encoding": "chunked"})
    report = {"status": "PASSED", "external_calls": 0, "search_calls": 0, "fixture_only": True,
              "model_quality_evaluated": False, "real_java_client": True, "requests": verification}
    (DIRECTORY / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report))
finally:
    for server in (proxy, fixture):
        server.shutdown()
        server.server_close()
