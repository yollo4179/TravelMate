"""Local OTLP transport capture; performs no evaluation, retrieval or inference."""
from __future__ import annotations

import argparse
import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from enum import StrEnum
import gzip
from http import HTTPStatus
import json
from pathlib import Path
from threading import Lock
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from google.protobuf.json_format import MessageToDict
from opentelemetry.proto.collector.trace.v1.trace_service_pb2 import ExportTraceServiceRequest
import uvicorn

MAX_BODY_BYTES = 8 * 1024 * 1024


class CaptureStatus(StrEnum):
    PROBE = "transport_probe_only"
    RECORDED = "recorded_not_scored"


class TraceCapture:
    def __init__(self, directory: Path) -> None:
        self.directory = directory
        self.lock = Lock()
        directory.mkdir(parents=True, exist_ok=True)

    def append(self, payload: bytes) -> None:
        request = ExportTraceServiceRequest.FromString(payload)
        document: dict[str, Any] = MessageToDict(request, preserving_proto_field_name=True)
        is_probe = any(span.name == "b_environment_transport_probe"
                       for resource in request.resource_spans for scope in resource.scope_spans for span in scope.spans)
        filename = "transport-probes.jsonl" if is_probe else "runtime-traces.jsonl"
        envelope = {"captured_at": datetime.now(UTC).isoformat(), "transport_probe": is_probe,
                    "quality_status": CaptureStatus.PROBE if is_probe else CaptureStatus.RECORDED, "otlp": document}
        with self.lock, (self.directory / filename).open("a", encoding="utf-8") as target:
            target.write(json.dumps(envelope, ensure_ascii=False) + "\n")


def create_application(directory: Path) -> FastAPI:
    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.capture = TraceCapture(directory)
        yield

    application = FastAPI(lifespan=lifespan)

    @application.get("/health")
    async def health() -> dict[str, str | bool]:
        return {"status": "ok", "inference": False}

    @application.post("/otel/v1/traces")
    async def capture_trace(request: Request) -> Response:
        payload = await request.body()
        if not payload or len(payload) > MAX_BODY_BYTES:
            raise HTTPException(HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        try:
            if request.headers.get("Content-Encoding") == "gzip":
                payload = gzip.decompress(payload)
            if len(payload) > MAX_BODY_BYTES:
                raise ValueError("Decompressed OTLP frame exceeds limit")
            await asyncio.to_thread(request.app.state.capture.append, payload)
        except Exception as exception:
            raise HTTPException(HTTPStatus.BAD_REQUEST, "Invalid OTLP frame") from exception
        return Response(content=b"", media_type="application/x-protobuf")

    return application


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    arguments = parser.parse_args()
    uvicorn.run(create_application(arguments.directory), host="0.0.0.0", port=4318)


if __name__ == "__main__":
    main()
