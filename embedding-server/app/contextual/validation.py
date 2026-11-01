"""보존 응답의 검증 규칙을 생성 프롬프트와 별도로 식별한다."""
from __future__ import annotations

from enum import StrEnum

from .prompts import resolve_prompt


class ValidationVersion(StrEnum):
    STRICT = "contextual-validation-v1"
    SUBJECT_ONLY = "contextual-validation-v2"
    OBSERVATIONS = "contextual-validation-v3"
    RELATIONS = "contextual-validation-v4"
    SERVER_EVIDENCE = "contextual-validation-v5"


class ExclusionReason(StrEnum):
    NO_SUBJECT = "no_subject"
    UNATTRIBUTED = "unattributed"
    INVALID_ATTRIBUTION = "invalid_attribution"
    UNRESOLVED_MOVEMENT = "unresolved_movement"


def current_validation_version(prompt_version: str) -> str:
    if resolve_prompt(prompt_version).server_evidence:
        return ValidationVersion.SERVER_EVIDENCE.value
    if resolve_prompt(prompt_version).independent_relations:
        return ValidationVersion.RELATIONS.value
    if resolve_prompt(prompt_version).supports_relations:
        return ValidationVersion.OBSERVATIONS.value
    return ValidationVersion.SUBJECT_ONLY.value


def resolve_validation_version(version: str | None, prompt_version: str) -> ValidationVersion:
    prompt = resolve_prompt(prompt_version)
    default = ValidationVersion.SERVER_EVIDENCE if prompt.server_evidence else (ValidationVersion.RELATIONS if prompt.independent_relations else ValidationVersion.STRICT)
    resolved = ValidationVersion(version) if version is not None else default
    if prompt.server_evidence and resolved != ValidationVersion.SERVER_EVIDENCE:
        raise ValueError("서버 인용 계약에는 서버 위치 검증 버전이 필요합니다")
    if (resolved in (ValidationVersion.RELATIONS, ValidationVersion.SERVER_EVIDENCE)) != prompt.independent_relations:
        raise ValueError("독립 관계 계약과 검증 버전이 일치해야 합니다")
    return resolved
