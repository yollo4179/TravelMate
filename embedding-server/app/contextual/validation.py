"""보존 응답의 검증 규칙을 생성 프롬프트와 별도로 식별한다."""
from __future__ import annotations

from enum import StrEnum

from .prompts import resolve_prompt


class ValidationVersion(StrEnum):
    STRICT = "contextual-validation-v1"
    SUBJECT_ONLY = "contextual-validation-v2"


class ExclusionReason(StrEnum):
    NO_SUBJECT = "no_subject"
    UNATTRIBUTED = "unattributed"


def current_validation_version(prompt_version: str) -> str:
    resolve_prompt(prompt_version)
    return ValidationVersion.SUBJECT_ONLY.value


def resolve_validation_version(version: str | None, prompt_version: str) -> ValidationVersion:
    resolve_prompt(prompt_version)
    return ValidationVersion(version) if version is not None else ValidationVersion.STRICT
