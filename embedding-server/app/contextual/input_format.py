"""문자 위치 해석을 모델에 맡기지 않는 선택형 입력 계약."""
from __future__ import annotations

from copy import deepcopy
from enum import StrEnum
from typing import Any


class InputVersion(StrEnum):
    OFFSETS = "source-offsets-v1"
    EXPLICIT = "source-explicit-chunks-v2"


def explicit_chunks(document: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(document)
    sources = {source["source_id"]: source for source in result["sources"]}
    if len(sources) != len(result["sources"]):
        raise ValueError("입력 문서의 source_id는 중복될 수 없습니다")
    for span in result["spans"]:
        source = sources[span["source_id"]]
        start, end = span["start"], span["end"]
        if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source["text"]):
            raise ValueError("청크 위치는 보존 원문의 Unicode 코드포인트 범위여야 합니다")
        quotation = source["text"][start:end]
        if "chunk_text" in span and span["chunk_text"] != quotation:
            raise ValueError("명시된 청크가 보존 원문의 해당 구간과 다릅니다")
        span["chunk_text"] = quotation
    return result
