"""TestLogPath 하나마다 기록 함수 하나. 모든 평가 단위가 같은 표를 쓴다.

대주제·소주제 구성과 순서는 log_types.TestLogPath와 같다. 다르면 불러올 때 실패한다.
"""
from __future__ import annotations
from pathlib import Path
from types import MappingProxyType
from typing import Any, Callable
from common.execution.control import RunControl
from common.dataset.io import write_json, write_jsonl
from tracks.conversation.log_types import TestLogPath
from tracks.conversation.review import export_review


class TestLogs:
        # 각 람다는 (실행 폴더 기준으로 해석된 경로, 기록할 값)을 받는다.

        # [1. 실행 식별]
        _RUN_IDENTITY = (
            #      (1-1) 실행 설정
            (TestLogPath.RUN, lambda path, value: write_json(path, value)),             # 시작 시 status=started로 쓰고, 종료 시 최종 상태로 다시 쓴다
            (TestLogPath.INPUTS, lambda path, value: write_jsonl(path, value)),         # 전송 전 한 번만 쓴다
            #      (1-2) 호출 원장: 파일을 직접 쓰지 않고 공통 RunControl을 만든다. 원장·횟수 상한을 구현체가 우회하지 못하게 한다
            (TestLogPath.ATTEMPTS, lambda path, value: RunControl(value["settings"], path, mock_responses=value["mock_responses"])),
            #      (1-3) 실행 서버 계약
            (TestLogPath.SERVER_CONTRACT, lambda path, value: write_json(path, value)), # 대화 요청 전에 받은 서버 계약
            (TestLogPath.SEARCH_CONTRACT, lambda path, value: write_json(path, value)), # 대화 요청 전에 받은 검색 서버 상태
        )

        # [2. 관측 원본]
        _OBSERVATIONS = (
            #      (2-1) 응답
            (TestLogPath.RECORDS, lambda path, value: write_jsonl(path, value)),        # 문항이 끝날 때마다 누적본 전체를 다시 쓴다
            #      (2-2) 서버 내부 관측
            (TestLogPath.EVENTS, lambda path, value: write_jsonl(path, value)),         # 종료 시 이번 실행의 requestId에 해당하는 이벤트만 쓴다
        )

        # [3. 판정]
        _JUDGMENTS = (
            #      (3-1) 기계적 검사
            (TestLogPath.SCORES, lambda path, value: write_jsonl(path, value)),
            #      (3-2) 의미 검수: 이미 있는 검수표는 덮어쓰지 않는다(export_review가 배타적 생성)
            (TestLogPath.REVIEW, lambda path, value: export_review(path, value)),
            #      (3-3) 요약
            (TestLogPath.SUMMARY, lambda path, value: write_json(path, value)),
        )

        ENTRIES = (*_RUN_IDENTITY, *_OBSERVATIONS, *_JUDGMENTS)
        WRITERS = MappingProxyType(dict(ENTRIES))

        @staticmethod
        def path(root: Path, kind: TestLogPath) -> Path:
            return root / TestLogPath(kind).value

        @classmethod
        def write(cls, root: Path, kind: TestLogPath, value: Any) -> Any:
            writer: Callable[[Path, Any], Any] = cls.WRITERS[TestLogPath(kind)]
            return writer(cls.path(root, kind), value)


if (len(TestLogPath.__members__) != len(TestLogPath)
        or tuple(kind for kind, _ in TestLogs.ENTRIES) != tuple(TestLogPath)
        or len(TestLogs.WRITERS) != len(TestLogPath)):
    raise RuntimeError("TestLogs.ENTRIES must pair every TestLogPath exactly once, in the same group order")
