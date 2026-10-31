"""Versioned prompts for source-preserving contextual generation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from . import v1_contextual_prompt, v2_contextual_prompt, v3_contextual_prompt


class PromptVersion(StrEnum):
    V1 = v1_contextual_prompt.PROMPT_VERSION
    V2 = v2_contextual_prompt.PROMPT_VERSION
    V3 = v3_contextual_prompt.PROMPT_VERSION


@dataclass(frozen=True)
class PromptDefinition:
    version: PromptVersion
    instructions: str
    require_empty_unattributed_entities: bool
    allow_hypothetical_questions: bool


DEFAULT_PROMPT_VERSION = PromptVersion.V2.value
PROMPTS = MappingProxyType({
    PromptVersion.V1: PromptDefinition(
        version=PromptVersion.V1,
        instructions=v1_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=False,
        allow_hypothetical_questions=True,
    ),
    PromptVersion.V2: PromptDefinition(
        version=PromptVersion.V2,
        instructions=v2_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
    ),
    PromptVersion.V3: PromptDefinition(
        version=PromptVersion.V3,
        instructions=v3_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
    ),
})


def resolve_prompt(version: str) -> PromptDefinition:
    try:
        return PROMPTS[PromptVersion(version)]
    except (KeyError, ValueError) as exception:
        raise ValueError(f"Unsupported contextual prompt version: {version}") from exception
