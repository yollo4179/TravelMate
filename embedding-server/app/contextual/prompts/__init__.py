"""Versioned prompts for source-preserving contextual generation."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from . import v1_contextual_prompt, v2_contextual_prompt, v3_contextual_prompt, v4_contextual_prompt, v5_contextual_prompt
from . import v6_contextual_prompt, v7_contextual_prompt


class PromptVersion(StrEnum):
    V1 = v1_contextual_prompt.PROMPT_VERSION
    V2 = v2_contextual_prompt.PROMPT_VERSION
    V3 = v3_contextual_prompt.PROMPT_VERSION
    V4 = v4_contextual_prompt.PROMPT_VERSION
    V5 = v5_contextual_prompt.PROMPT_VERSION
    V6 = v6_contextual_prompt.PROMPT_VERSION
    V7 = v7_contextual_prompt.PROMPT_VERSION


@dataclass(frozen=True)
class PromptDefinition:
    version: PromptVersion
    instructions: str
    require_empty_unattributed_entities: bool
    allow_hypothetical_questions: bool
    requires_explicit_chunks: bool = False
    supports_relations: bool = False
    independent_relations: bool = False


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
    PromptVersion.V4: PromptDefinition(
        version=PromptVersion.V4,
        instructions=v4_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
    ),
    PromptVersion.V5: PromptDefinition(
        version=PromptVersion.V5,
        instructions=v5_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
        requires_explicit_chunks=True,
    ),
    PromptVersion.V6: PromptDefinition(
        version=PromptVersion.V6,
        instructions=v6_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
        requires_explicit_chunks=True,
        supports_relations=True,
    ),
    PromptVersion.V7: PromptDefinition(
        version=PromptVersion.V7,
        instructions=v7_contextual_prompt.INSTRUCTIONS,
        require_empty_unattributed_entities=True,
        allow_hypothetical_questions=False,
        requires_explicit_chunks=True,
        supports_relations=True,
        independent_relations=True,
    ),
})


def resolve_prompt(version: str) -> PromptDefinition:
    try:
        return PROMPTS[PromptVersion(version)]
    except (KeyError, ValueError) as exception:
        raise ValueError(f"Unsupported contextual prompt version: {version}") from exception
