"""Bound every external attempt and keep MOCK transports separate from LIVE calls."""
from __future__ import annotations

from collections import Counter
import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import json
import math
import os
from pathlib import Path
import time
from typing import Any, Awaitable, Callable, Protocol
import uuid

from common.dataset.io import canonical_digest, digest, read_json
from common.paths import EVALUATION_ROOT


class RunMode(StrEnum):
    LIVE = "LIVE"
    MOCK = "MOCK"


class Operation(StrEnum):
    SEARCH = "search"
    JUDGE = "judge"
    RUNTIME_READ = "runtime_read"
    OBSERVATION_READ = "observation_read"
    PUBLISH = "publish"


class AttemptStatus(StrEnum):
    STARTED = "started"
    COMPLETED = "completed"
    FAILED = "failed"
    NOT_RUN = "not_run"


class ExecutionBlocked(RuntimeError):
    pass


ExternalCall = Callable[[], Awaitable[dict[str, Any]]]


@dataclass(frozen=True, kw_only=True)
class ExecutionSettings:
    mode: RunMode
    case_ids: tuple[str, ...]
    max_calls: dict[Operation, int]
    timeout_seconds: float
    model: str | None
    max_output_tokens: int | None
    parameters: dict[str, Any]
    configuration_sha256: str

    @classmethod
    def load(cls, path: Path) -> ExecutionSettings:
        configuration = read_json(path)
        required = {"mode", "case_ids", "max_calls", "timeout_seconds", "model", "max_output_tokens", "parameters"}
        if not isinstance(configuration, dict) or set(configuration) != required:
            raise ValueError("Execution configuration must explicitly specify exactly the documented fields")
        case_ids = configuration["case_ids"]
        if not isinstance(case_ids, list) or not case_ids or any(not isinstance(value, str) or not value.strip() for value in case_ids):
            raise ValueError("Explicit nonempty case IDs are required")
        if len(set(case_ids)) != len(case_ids):
            raise ValueError("Duplicate execution case IDs")
        limits = configuration["max_calls"]
        if not isinstance(limits, dict) or any(type(value) is not int or value < 0 for value in limits.values()):
            raise ValueError("Call caps must be nonnegative integers; omitted operations have zero budget")
        max_calls = {Operation(name): value for name, value in limits.items()}
        timeout = configuration["timeout_seconds"]
        if type(timeout) not in (int, float) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("A finite positive attempt timeout is required")
        model = configuration["model"]
        output_tokens = configuration["max_output_tokens"]
        if model is not None and (not isinstance(model, str) or not model.strip()):
            raise ValueError("The model must be explicitly named or null")
        if output_tokens is not None and (type(output_tokens) is not int or output_tokens <= 0):
            raise ValueError("Output reservation must be a positive integer or null")
        if max_calls.get(Operation.JUDGE, 0) and (model is None or output_tokens is None):
            raise ValueError("Judge calls require an explicit model and output reservation")
        if not isinstance(configuration["parameters"], dict):
            raise ValueError("Execution parameters must be an object")
        return cls(
            mode=RunMode(configuration["mode"]),
            case_ids=tuple(case_ids),
            max_calls=max_calls,
            timeout_seconds=float(timeout),
            model=model,
            max_output_tokens=output_tokens,
            parameters=configuration["parameters"],
            configuration_sha256=digest(path),
        )

    def require_scope(self, case_ids: list[str]) -> None:
        if len(case_ids) != len(set(case_ids)) or set(case_ids) != set(self.case_ids):
            raise ExecutionBlocked("Selected inputs must match the explicit execution case IDs")

    def require_capacity(self, operation: Operation, maximum_attempts: int) -> None:
        if maximum_attempts > self.max_calls.get(operation, 0):
            raise ExecutionBlocked(f"Planned {operation.value} attempts exceed the explicit call cap")

    def parameter(self, name: str) -> Any:
        if name not in self.parameters:
            raise ExecutionBlocked(f"Missing explicit execution parameter: {name}")
        return self.parameters[name]


class ExecutionStrategy(Protocol):
    def supports(self, mode: RunMode) -> bool: ...

    async def execute(self, request_hash: str, call: ExternalCall) -> dict[str, Any]: ...


class LiveExecutionStrategy:
    def supports(self, mode: RunMode) -> bool:
        return mode == RunMode.LIVE

    async def execute(self, request_hash: str, call: ExternalCall) -> dict[str, Any]:
        return await call()


class MockExecutionStrategy:
    def __init__(self, responses: dict[str, dict[str, Any]]) -> None:
        self.responses = responses

    def supports(self, mode: RunMode) -> bool:
        return mode == RunMode.MOCK

    async def execute(self, request_hash: str, call: ExternalCall) -> dict[str, Any]:
        if request_hash not in self.responses:
            raise ExecutionBlocked("No explicit MOCK response exists for this exact request hash")
        fixture = self.responses[request_hash]
        if fixture.get("error_type"):
            raise ExecutionBlocked(f"MOCK failure: {fixture['error_type']}")
        result = fixture.get("response")
        if not isinstance(result, dict):
            raise ExecutionBlocked("A MOCK response must be a recorded object")
        return result


class RunControl:
    def __init__(
        self,
        settings: ExecutionSettings,
        ledger_path: Path,
        *,
        mock_responses: dict[str, dict[str, Any]] | None = None,
    ) -> None:
        self.settings = settings
        self.ledger_path = ledger_path
        self.counts: Counter[Operation] = Counter()
        self.stopped = False
        self.events: list[dict[str, Any]] = []
        self.last_attempt: dict[str, Any] | None = None
        strategies: list[ExecutionStrategy] = [LiveExecutionStrategy(), MockExecutionStrategy(mock_responses or {})]
        supported = [strategy for strategy in strategies if strategy.supports(settings.mode)]
        if len(supported) != 1:
            raise ExecutionBlocked("Exactly one execution strategy must support the configured mode")
        self.strategy = supported[0]
        ledger_path.parent.mkdir(parents=True, exist_ok=True)
        # A fresh journal prevents a restarted process from resetting a spent budget.
        with ledger_path.open("x", encoding="utf-8"):
            pass

    def record(self, event: dict[str, Any]) -> None:
        event = {**event, "recorded_at_utc": datetime.now(timezone.utc).isoformat()}
        serialized = json.dumps(event, ensure_ascii=False, allow_nan=False) + "\n"
        with self.ledger_path.open("a", encoding="utf-8", newline="\n") as journal:
            journal.write(serialized)
            journal.flush()
            os.fsync(journal.fileno())
        self.events.append(event)
        self.last_attempt = event

    async def execute(
        self,
        operation: Operation,
        case_id: str,
        request: dict[str, Any],
        call: ExternalCall,
    ) -> dict[str, Any]:
        request_hash = canonical_digest(request)
        attempt = {
            "attempt_id": str(uuid.uuid4()),
            "operation": operation.value,
            "case_id": case_id,
            "execution_mode": self.settings.mode.value,
            "configuration_sha256": self.settings.configuration_sha256,
            "request_sha256": request_hash,
            "request": request,
        }
        if self.stopped or case_id not in self.settings.case_ids or self.counts[operation] >= self.settings.max_calls.get(operation, 0):
            self.record({**attempt, "status": AttemptStatus.NOT_RUN.value, "dispatched": False, "duration_ms": None, "reason": "stopped_scope_or_call_cap"})
            self.stopped = True
            raise ExecutionBlocked("Execution stopped, case not selected, or call cap exhausted")
        self.counts[operation] += 1
        dispatched = self.settings.mode == RunMode.LIVE
        self.record({**attempt, "status": AttemptStatus.STARTED.value, "dispatched": dispatched, "mock_attempt": not dispatched})
        started = time.perf_counter()
        try:
            async with asyncio.timeout(self.settings.timeout_seconds):
                result = await self.strategy.execute(request_hash, call)
        except BaseException as exception:
            self.stopped = True
            self.record({
                **attempt,
                "status": AttemptStatus.FAILED.value,
                "dispatched": dispatched,
                "mock_attempt": not dispatched,
                "duration_ms": (time.perf_counter() - started) * 1000,
                "error_type": type(exception).__name__,
                "provider_request_id": getattr(exception, "request_id", None),
            })
            raise
        self.record({
            **attempt,
            "status": AttemptStatus.COMPLETED.value,
            "dispatched": dispatched,
            "mock_attempt": not dispatched,
            "duration_ms": (time.perf_counter() - started) * 1000,
            "response": result,
        })
        return result

    def summary(self) -> dict[str, Any]:
        return {
            "execution_mode": self.settings.mode.value,
            "configuration_sha256": self.settings.configuration_sha256,
            "call_caps": {operation.value: cap for operation, cap in self.settings.max_calls.items()},
            "attempt_counts": {operation.value: count for operation, count in self.counts.items()},
            "real_dispatch_count": sum(event["status"] == AttemptStatus.STARTED and event["dispatched"] for event in self.events),
            "stopped": self.stopped,
        }

    def reject_result(self, error_type: str) -> None:
        self.stopped = True
        if self.last_attempt is not None:
            self.record({**self.last_attempt, "status": AttemptStatus.FAILED.value, "validation_error_type": error_type})


def load_control(configuration_path: Path, output: Path, mock_path: Path | None) -> RunControl:
    if output.exists() or output.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
        raise FileExistsError("Execution needs a new output directory outside frozen datasets")
    settings = ExecutionSettings.load(configuration_path)
    if (settings.mode == RunMode.MOCK) != (mock_path is not None):
        raise ExecutionBlocked("MOCK requires a fixture file; LIVE forbids a MOCK fixture file")
    responses = read_json(mock_path) if mock_path is not None else None
    if responses is not None and not isinstance(responses, dict):
        raise ValueError("MOCK fixtures must map exact request hashes to response objects")
    return RunControl(settings, output / "attempts.jsonl", mock_responses=responses)
