"""Test the existing recorder comparison using preserved real request bytes, without sockets."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import threading
from typing import Any, Callable
from unittest.mock import patch

DIRECTORY = Path(__file__).resolve().parent
RUNTIME = DIRECTORY.parent
PREVIOUS = RUNTIME.parent / "openai-strict-live-20261103-03"
SPEC = importlib.util.spec_from_file_location("approved_recorder", RUNTIME / "run-once.py")
assert SPEC and SPEC.loader
recorder = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(recorder)
original_path = PREVIOUS / "results/received-01.request.json"
original_bytes = original_path.read_bytes()
original_sha256 = hashlib.sha256(original_bytes).hexdigest()
original_request = json.loads(original_bytes)
expected_schema = json.loads((RUNTIME / "provider-schema.expected.json").read_bytes())


def category(schema: dict[str, Any]) -> dict[str, Any]:
    return schema["properties"]["category"]["anyOf"][0]


def reverse_required(schema: Any) -> None:
    if isinstance(schema, dict):
        for name, value in schema.items():
            if name == "required" and isinstance(value, list):
                value.reverse()
            else:
                reverse_required(value)
    elif isinstance(schema, list):
        for item in schema:
            reverse_required(item)


matrix: list[tuple[str, bool, Callable[[dict[str, Any]], Any] | None]] = [
    ("preserved_real_request_required_order", True, None),
    ("nested_required_order", True, reverse_required),
    ("required_field_removed", False, lambda schema: schema["required"].pop()),
    ("required_field_added", False, lambda schema: schema["required"].append("unexpected_required")),
    ("required_field_duplicated", False, lambda schema: schema["required"].append(schema["required"][0])),
    ("category_enum_removed", False, lambda schema: category(schema)["enum"].pop()),
    ("category_enum_added", False, lambda schema: category(schema)["enum"].append("INVALID_CATEGORY")),
    ("category_enum_order_changed", False, lambda schema: category(schema)["enum"].reverse()),
    ("category_type_changed", False, lambda schema: category(schema).__setitem__("type", "integer")),
    ("additional_fields_allowed", False, lambda schema: schema.__setitem__("additionalProperties", True)),
    ("nested_additional_fields_allowed", False,
     lambda schema: schema["properties"]["area"]["anyOf"][0].__setitem__("additionalProperties", True)),
    ("required_type_changed", False, lambda schema: schema.__setitem__("required", "query")),
]
observations: list[dict[str, Any]] = []
for case_name, should_pass, mutation in matrix:
    request = copy.deepcopy(original_request)
    if mutation:
        mutation(request["tools"][0]["parameters"])
    request_bytes = original_bytes if mutation is None else json.dumps(request, ensure_ascii=False).encode("utf-8")
    snapshot = copy.deepcopy(request)
    recorder.RESULTS = DIRECTORY / case_name
    recorder.RESULTS.mkdir()
    recorder.COUNTERS = {"/v1/responses/input_tokens": 0, "/v1/responses": 0}
    recorder.HALTED = threading.Event()
    forwarded: list[bytes] = []
    status: list[int] = []

    class OfflineClient:
        def __init__(self, **arguments: Any) -> None:
            pass

        def __enter__(self) -> OfflineClient:
            return self

        def __exit__(self, *arguments: Any) -> None:
            pass

        def post(self, url: str, *, headers: dict[str, str], content: bytes) -> Any:
            forwarded.append(content)
            return recorder.httpx.Response(
                200,
                headers={"Content-Type": "application/json"},
                content=b'{"object":"response.input_tokens","input_tokens":1}',
            )

    handler = object.__new__(recorder.Recorder)
    handler.path = "/v1/responses/input_tokens"
    handler.headers = {"Content-Length": str(len(request_bytes)), "Authorization": "OFFLINE-NOT-A-KEY"}
    handler.rfile = io.BytesIO(request_bytes)
    handler.wfile = io.BytesIO()
    handler.send_response = lambda code: status.append(code)
    handler.send_header = lambda *arguments: None
    handler.end_headers = lambda: None
    handler.send_error = lambda code, message: status.append(code)
    with patch.object(recorder.httpx, "Client", OfflineClient):
        handler.do_POST()
    assert status == ([200] if should_pass else [400]), (case_name, status)
    assert forwarded == ([request_bytes] if should_pass else []), case_name
    assert (recorder.RESULTS / "received-01.request.json").read_bytes() == request_bytes
    assert request == snapshot
    assert json.loads((RUNTIME / "provider-schema.expected.json").read_bytes()) == expected_schema
    assert recorder.HALTED.is_set() is not should_pass
    if should_pass:
        assert (recorder.RESULTS / "01-count.request.json").read_bytes() == request_bytes
    observations.append({"case": case_name, "accepted": should_pass,
                         "raw_request_sha256": hashlib.sha256(request_bytes).hexdigest(),
                         "raw_request_preserved": True, "external_calls": 0})

assert original_path.read_bytes() == original_bytes
assert hashlib.sha256(original_path.read_bytes()).hexdigest() == original_sha256
report = {"status": "PASSED", "tests": len(observations), "failures": 0,
          "external_calls": 0, "preserved_actual_request_sha256": original_sha256,
          "previous_request_bytes_and_hash_unchanged": True, "cases": observations}
(DIRECTORY / "verification.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
print(json.dumps(report))
