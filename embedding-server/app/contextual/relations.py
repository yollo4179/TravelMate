"""관찰 귀속과 독립적인 이동 관계의 계약을 검증한다."""
from __future__ import annotations

from enum import StrEnum
from typing import Any


class RelationType(StrEnum):
    MOVEMENT = "movement"


class RelationImportance(StrEnum):
    PRIMARY = "primary"
    SUPPORTING = "supporting"


class RetrievalScope(StrEnum):
    RELATION = "relation"


class ActiveChunkRole(StrEnum):
    SUBJECT = "subject"
    RELATION_ENDPOINT = "relation_endpoint"


def independent_relations(relations: list[dict[str, Any]]) -> bool:
    return bool(relations) and all({"type", "importance", "evidence"}.issubset(relation) for relation in relations)


def endpoint_ids(relations: list[dict[str, Any]]) -> set[int]:
    return {endpoint["place_id"] for relation in relations
            for endpoint in (relation["origin"], relation["destination"]) if endpoint["place_id"] is not None}


def validate_independent_relations(
    relations: list[dict[str, Any]],
    references: list[dict[str, Any]],
    source_text: str,
    start: int,
    end: int,
) -> None:
    reference_ids = {reference["place_id"] for reference in references}
    for relation in relations:
        RelationType(relation["type"])
        RelationImportance(relation["importance"])
        evidence = relation["evidence"]
        left, right = evidence["start"], evidence["end"]
        if type(left) is not int or type(right) is not int or not start <= left < right <= end:
            raise ValueError("관계 근거 위치는 현재 청크 안의 연속 원문 구간이어야 합니다")
        if source_text[left:right] != evidence["quote"] or not evidence["quote"].strip():
            raise ValueError("관계 근거는 위치가 일치하는 정확한 원문이어야 합니다")
        for endpoint in (relation["origin"], relation["destination"]):
            identifier = endpoint["place_id"]
            if identifier is not None and (type(identifier) is not int or identifier not in reference_ids):
                raise ValueError("알려진 관계 참가자는 장소 참조에 보존해야 합니다. subject일 필요는 없습니다")
        if any(not condition["quote"] or condition["quote"] not in evidence["quote"] for condition in relation["conditions"]):
            raise ValueError("이동 조건은 해당 관계 근거 안의 정확한 원문이어야 합니다")
