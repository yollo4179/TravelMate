"""관계의 정확한 인용을 현재 청크에서 유일하게 찾아 서버 위치를 계산한다."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class GroundingVersion(StrEnum):
    EXACT_UNIQUE = "relation-quote-exact-unique-v1"


class GroundingStatus(StrEnum):
    RESOLVED = "resolved"
    NOT_FOUND = "quote_not_found"
    AMBIGUOUS = "quote_ambiguous"
    EMPTY = "quote_empty"


@dataclass(frozen=True)
class GroundedChunk:
    chunk: dict[str, Any]
    audit: list[dict[str, Any]]
    error: str | None


def ground_relation_evidence(chunk: dict[str, Any], source_text: str) -> GroundedChunk:
    normalized = deepcopy(chunk)
    audit: list[dict[str, Any]] = []
    errors: list[str] = []
    start, end = chunk["start"], chunk["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= len(source_text):
        raise ValueError("인용 위치 계산 전 청크의 보존 원문 범위를 검증해야 합니다")
    chunk_text = source_text[start:end]
    for index, relation in enumerate(normalized["relations"]):
        evidence = relation["evidence"]
        quote = evidence["quote"]
        left = chunk_text.find(quote) if quote.strip() else -1
        status = GroundingStatus.RESOLVED
        if not quote.strip():
            status = GroundingStatus.EMPTY
        elif left < 0:
            status = GroundingStatus.NOT_FOUND
        # 겹치는 중복도 모호하므로 인용 길이만큼 건너뛰지 않는다.
        elif chunk_text.find(quote, left + 1) >= 0:
            status = GroundingStatus.AMBIGUOUS
        computed = {"start": start + left, "end": start + left + len(quote)} if status == GroundingStatus.RESOLVED else None
        audit.append({"source_id": chunk["source_id"], "chunk_span": {"start": start, "end": end},
                      "relation_index": index, "rule_version": GroundingVersion.EXACT_UNIQUE.value,
                      "status": status.value, "quote": quote,
                      "model_evidence": deepcopy(evidence), "server_span": computed})
        if computed is None:
            errors.append(status.value)
            continue
        relation["evidence"] = {**computed, "quote": quote}
    return GroundedChunk(normalized, audit, "; ".join(errors) if errors else None)
