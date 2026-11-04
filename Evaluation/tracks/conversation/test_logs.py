"""One enum/function pair per artifact, shared by every evaluation stage."""
from __future__ import annotations
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from common.execution.control import RunControl
from common.dataset.io import write_json, write_jsonl
from tracks.conversation.log_types import TestLogPath
from tracks.conversation.review import export_review


class TestLogs:
        # JSON identities and final summaries. Each lambda receives a resolved output path.
        _JSON = (
            (TestLogPath.RUN, lambda path, value: write_json(path, value)),
            (TestLogPath.SEARCH_CONTRACT, lambda path, value: write_json(path, value)),
            (TestLogPath.SERVER_CONTRACT, lambda path, value: write_json(path, value)),
            (TestLogPath.SUMMARY, lambda path, value: write_json(path, value)),
        )
        # 이 쌍은 공통 RunControl을 생성한다. 전송 전 원장 기록·횟수 상한은 동일 실행 경로에서 관리한다.
        _RECORDS = (
            (TestLogPath.ATTEMPTS, lambda path, value: RunControl(value["settings"], path, mock_responses=value["mock_responses"])),
            (TestLogPath.INPUTS, lambda path, value: write_jsonl(path, value)),
            (TestLogPath.RECORDS, lambda path, value: write_jsonl(path, value)),
            (TestLogPath.EVENTS, lambda path, value: write_jsonl(path, value)),
        )
        # Deterministic scores and separate, hash-bound human semantic review.
        _JUDGMENTS = (
            (TestLogPath.SCORES, lambda path, value: write_jsonl(path, value)),
            (TestLogPath.REVIEW, lambda path, value: export_review(path, value)),
        )
        ENTRIES = (*_JSON, *_RECORDS, *_JUDGMENTS)
        WRITERS = MappingProxyType(dict(ENTRIES))

        @staticmethod
        def path(root: Path, kind: TestLogPath) -> Path:
            return root / TestLogPath(kind).value

        @classmethod
        def write(cls, root: Path, kind: TestLogPath, value: Any) -> Any:
            writer: Callable[[Path, Any], Any] = cls.WRITERS[TestLogPath(kind)]
            return writer(cls.path(root, kind), value)


if len(TestLogPath.__members__) != len(TestLogPath) or len(TestLogs.ENTRIES) != len(TestLogPath) or set(TestLogs.WRITERS) != set(TestLogPath):
    raise RuntimeError("Every TestLogPath must have exactly one paired log function")
