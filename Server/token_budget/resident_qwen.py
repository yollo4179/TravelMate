"""Resident vocabulary-only resources and a serial, correlated JSONL protocol."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from enum import StrEnum
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import struct
import subprocess
import time
from typing import Any, BinaryIO
import uuid

from Server.token_budget.exact_qwen_counter import (
    LIBRARY_SHA256, MODEL_DIGEST, MODEL_SHA256, RENDERER_SHA256, TEMPLATE_SHA256,
    digest, load_verified_assets, validate_identity,
)
from Server.token_budget.qwen_tokenization import NativeQwenVocabulary, independent_byte_bpe

MAX_FRAME_BYTES = 16 * 1024 * 1024


class Operation(StrEnum):
    INIT = "INIT"
    COUNT = "COUNT"


class Status(StrEnum):
    READY = "READY"
    COUNTED = "COUNTED"
    ERROR = "ERROR"


class ErrorCode(StrEnum):
    ASSET_CHANGED = "ASSET_CHANGED"
    IDENTITY_REJECTED = "IDENTITY_REJECTED"
    CALCULATION_FAILED = "CALCULATION_FAILED"
    CALCULATION_TIMEOUT = "CALCULATION_TIMEOUT"
    PROTOCOL_ERROR = "PROTOCOL_ERROR"


class IdentityChangedError(ValueError):
    pass


class MetadataIdentityError(ValueError):
    pass


class ProtocolError(ValueError):
    pass


def validate_metadata(envelope: dict[str, Any]) -> None:
    try:
        validate_identity(envelope)
    except (ValueError, KeyError, TypeError) as exception:
        raise MetadataIdentityError("Unsupported model, template or request identity") from exception


def asset_fingerprints(profile: dict[str, str]) -> dict[str, tuple[int, ...]]:
    paths = [Path(profile[key]).absolute() for key in ("model_path", "renderer_path", "manifest_path")]
    paths.append(Path(profile["library_directory"]).absolute() / "libllama.dll")
    if profile.get("profile_path"):
        paths.append(Path(profile["profile_path"]).absolute())
    signatures = {}
    for path in paths:
        stat = path.stat()
        signatures[str(path)] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
    return signatures


class PersistentRenderer:
    def __init__(self, renderer: Path) -> None:
        self._process = subprocess.Popen(
            [str(renderer.resolve())],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
        )
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="qwen-renderer")

    def render(self, envelope: dict[str, Any], request_id: str) -> dict[str, Any]:
        encoded = ('{"key":' + json.dumps(request_id) + ',"wire":' + envelope["wire"] + ',"template":'
                   + json.dumps(envelope["show"]["template"], ensure_ascii=False)
                   + ',"template_source":"go_template"}\n').encode("utf-8")
        if len(encoded) > MAX_FRAME_BYTES:
            raise ValueError("Complete renderer frame exceeds the supported limit")

        def exchange() -> dict[str, Any]:
            if self._process.poll() is not None or self._process.stdin is None or self._process.stdout is None:
                raise RuntimeError("Renderer is unavailable")
            self._process.stdin.write(encoded)
            self._process.stdin.flush()
            response = self._process.stdout.readline(MAX_FRAME_BYTES * 2 + 1)
            if not response.endswith(b"\n") or len(response) > MAX_FRAME_BYTES * 2:
                raise ValueError("Incomplete or oversized renderer result")
            return json.loads(response)

        future = self._executor.submit(exchange)
        try:
            rendered = future.result(timeout=30)
        except Exception:
            self.close()
            raise
        if (rendered.get("key") != request_id or rendered.get("wire_sha256") != digest(envelope["wire"])
                or rendered.get("template_sha256") != TEMPLATE_SHA256
                or digest(rendered["prompt"]) != rendered.get("prompt_sha256")):
            raise ValueError("Rendered input identity mismatch")
        return rendered

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.kill()
        self._process.wait(timeout=5)
        for stream in (self._process.stdin, self._process.stdout):
            if stream is not None:
                stream.close()
        self._executor.shutdown(wait=True, cancel_futures=True)


class QwenTokenizerSession:
    def __init__(self, profile: dict[str, str], envelope: dict[str, Any]) -> None:
        started = time.perf_counter()
        validate_metadata(envelope)
        if importlib.metadata.version("tokenizers") != "0.22.2":
            raise ValueError("Unsupported independent tokenizer version")
        self.profile = dict(profile)
        self.session_id = str(uuid.uuid4())
        self.sequence = 0
        self.native: NativeQwenVocabulary | None = None
        self.independent: Any = None
        self.renderer: PersistentRenderer | None = None
        self.closed = False
        self.fingerprints = asset_fingerprints(self.profile)
        try:
            assets = load_verified_assets(self.profile)
            self.native = NativeQwenVocabulary(assets.libraries, assets.model, LIBRARY_SHA256)
            if self.native.special_policy() != {"add_bos": False, "add_eos": False, "vocabulary_size": 151936}:
                raise ValueError("Unsupported special token policy")
            self.independent = independent_byte_bpe(assets.metadata, self.native.special_tokens())
            self.renderer = PersistentRenderer(assets.renderer)
            self._check_assets()
        except Exception:
            self.close()
            raise
        self.initialization_ms = (time.perf_counter() - started) * 1000

    def _check_assets(self) -> None:
        if self.closed or asset_fingerprints(self.profile) != self.fingerprints:
            raise IdentityChangedError("Verified files changed; reinitialization is required")
        if importlib.metadata.version("tokenizers") != "0.22.2":
            raise IdentityChangedError("Tokenizer installation changed")

    def ready(self) -> dict[str, Any]:
        return {"workerSessionId": self.session_id, "workerPid": os.getpid(),
                "initializationMs": self.initialization_ms, "initializationCount": 1,
                "modelDigest": MODEL_DIGEST, "templateSha256": TEMPLATE_SHA256}

    def count(self, envelope: dict[str, Any], request_id: str) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            validate_metadata(envelope)
            self._check_assets()
            if self.native is None or self.independent is None or self.renderer is None:
                raise RuntimeError("Tokenizer session is unavailable")
            rendered = self.renderer.render(envelope, request_id)
            prompt = rendered["prompt"]
            identifiers = self.native.encode(prompt)
            if (identifiers != self.independent.encode(prompt, add_special_tokens=False).ids
                    or self.native.decode(identifiers, len(prompt.encode())) != prompt.encode()):
                raise ValueError("Token ID cross-check or full original byte roundtrip failed")
            self._check_assets()
            self.sequence += 1
            return {"inputTokens": len(identifiers), "wireSha256": digest(envelope["wire"]),
                    "templateSha256": TEMPLATE_SHA256, "promptSha256": digest(prompt),
                    "tokenIdsSha256": hashlib.sha256(struct.pack("<" + str(len(identifiers)) + "i", *identifiers)).hexdigest(),
                    "modelDigest": MODEL_DIGEST, "modelSha256": MODEL_SHA256,
                    "librarySha256": LIBRARY_SHA256, "rendererSha256": RENDERER_SHA256,
                    "serverVersion": "0.40.13", "nativeContextTokens": 40960,
                    "quality": "EXACT_LOCAL_CROSSCHECKED", "tokenizer": "gpt2/qwen2;b11963;tokenizers=0.22.2",
                    "inferenceDispatched": False, **self.ready(), "sequence": self.sequence,
                    "calculationMs": (time.perf_counter() - started) * 1000}
        except Exception:
            self.close()
            raise

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            if self.renderer is not None:
                self.renderer.close()
        finally:
            try:
                if self.native is not None:
                    self.native.close()
            finally:
                self.native = None
                self.independent = None
                self.renderer = None


def serve(profile: dict[str, str], source: BinaryIO, destination: BinaryIO) -> None:
    session: QwenTokenizerSession | None = None
    try:
        while line := source.readline(MAX_FRAME_BYTES + 1):
            request_id = None
            operation = None
            try:
                if len(line) > MAX_FRAME_BYTES or not line.endswith(b"\n"):
                    raise ValueError("Complete protocol frame exceeds the supported limit")
                frame = json.loads(line)
                request_id = frame["requestId"]
                if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
                    raise ValueError("Invalid request identity")
                operation = Operation(frame["operation"])
                if operation == Operation.INIT:
                    if session is not None:
                        raise ProtocolError("Session is already initialized")
                    session = QwenTokenizerSession(profile, frame["payload"])
                    payload, status = session.ready(), Status.READY
                else:
                    if session is None:
                        raise ProtocolError("INIT must precede COUNT")
                    payload, status = session.count(frame["payload"], request_id), Status.COUNTED
                response = {"requestId": request_id, "sessionId": session.session_id, "status": status, "payload": payload}
            except Exception as exception:
                code = ErrorCode.CALCULATION_FAILED
                if isinstance(exception, IdentityChangedError):
                    code = ErrorCode.ASSET_CHANGED
                if isinstance(exception, MetadataIdentityError):
                    code = ErrorCode.IDENTITY_REJECTED
                if isinstance(exception, TimeoutError):
                    code = ErrorCode.CALCULATION_TIMEOUT
                if operation is None or isinstance(exception, ProtocolError):
                    code = ErrorCode.PROTOCOL_ERROR
                response = {"requestId": request_id, "status": Status.ERROR, "errorCode": code,
                            "errorType": type(exception).__name__}
                destination.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
                destination.flush()
                return
            destination.write(json.dumps(response, ensure_ascii=False).encode("utf-8") + b"\n")
            destination.flush()
            del frame, payload, response, line
    finally:
        if session is not None:
            session.close()
