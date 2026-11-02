"""Mock transport tests; never export to a model or external trace service."""
from __future__ import annotations

import gzip
import json
from pathlib import Path
import sys
import tempfile
import unittest

from fastapi.testclient import TestClient
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from otlp_sink import TraceCapture, create_application


def probe_frame() -> bytes:
    packet = ExportTraceServiceRequest()
    span = packet.resource_spans.add().scope_spans.add().spans.add()
    span.name = "b_environment_transport_probe"
    span.trace_id = b"\x01" * 16
    span.span_id = b"\x02" * 8
    return packet.SerializeToString()


class CaptureTests(unittest.TestCase):
    def test_mock_packets_are_persisted_separately_from_runtime_traces(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            capture = TraceCapture(Path(directory))
            capture.append(probe_frame())
            result = json.loads((Path(directory) / "transport-probes.jsonl").read_text(encoding="utf-8"))
            self.assertTrue(result["transport_probe"])
            self.assertEqual("transport_probe_only", result["quality_status"])
            self.assertFalse((Path(directory) / "runtime-traces.jsonl").exists())

    def test_invalid_protobuf_fails_without_recording_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory, TestClient(create_application(Path(directory))) as client:
            self.assertEqual(400, client.post("/otel/v1/traces", content=b"not protobuf").status_code)
            self.assertFalse(list(Path(directory).glob("*.jsonl")))

    def test_lifespan_capture_accepts_gzip_without_external_calls(self) -> None:
        with tempfile.TemporaryDirectory() as directory, TestClient(create_application(Path(directory))) as client:
            response = client.post("/otel/v1/traces", content=gzip.compress(probe_frame()), headers={"Content-Encoding": "gzip"})
            self.assertEqual(200, response.status_code)
            self.assertEqual("application/x-protobuf", response.headers["content-type"])
            self.assertTrue((Path(directory) / "transport-probes.jsonl").is_file())


if __name__ == "__main__":
    unittest.main()
