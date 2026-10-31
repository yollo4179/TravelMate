"""Agent contextualization of supplied source spans, without replacing quotations."""
from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from app.enrichment.agent import AGENT_ENDPOINT, AgentSettings
from app.enrichment.contracts import ExistingPlace
from .contracts import PlaceRole, SearchChunk, SourceDocument, SPLITTER_VERSION, SplitterVersion
from .contracts import ContentKind, MovementCondition
from .relations import RelationType, RelationImportance, endpoint_ids, validate_independent_relations
from .pipeline import split_source
from .input_format import InputVersion, explicit_chunks
from .prompts import DEFAULT_PROMPT_VERSION, resolve_prompt
from .validation import ValidationVersion, resolve_validation_version

PROMPT_VERSION = DEFAULT_PROMPT_VERSION
INSTRUCTIONS = resolve_prompt(PROMPT_VERSION).instructions
DEFAULT_PRESET = "sonar-pro"

REFERENCE_SCHEMA = {"type": "object", "additionalProperties": False,
                    "required": ["place_id", "role"], "properties": {
                        "place_id": {"type": "integer", "minimum": 1},
                        "role": {"type": "string", "enum": [role.value for role in PlaceRole]}}}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["chunks"], "properties": {
    "chunks": {"type": "array", "items": {"type": "object", "additionalProperties": False,
        "required": ["source_id", "start", "end", "context_text", "place_refs", "entities", "hypothetical_questions"],
        "properties": {"source_id": {"type": "string"}, "start": {"type": "integer"}, "end": {"type": "integer"},
            "context_text": {"type": "string", "minLength": 1, "maxLength": 600},
            "place_refs": {"type": "array", "items": REFERENCE_SCHEMA},
            "entities": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                "required": ["name", "place_id", "role"], "properties": {
                    "name": {"type": "string"}, **REFERENCE_SCHEMA["properties"]}}},
            "hypothetical_questions": {"type": "array", "maxItems": 5, "items": {"type": "string"}},
        }}}}}

SCHEMA_V6 = deepcopy(SCHEMA)
_chunk_schema = SCHEMA_V6["properties"]["chunks"]["items"]
_chunk_schema["required"] += ["content_kind", "relations"]
_endpoint_schema = {"type": "object", "additionalProperties": False, "required": ["place_id", "name"],
                    "properties": {"place_id": {"type": ["integer", "null"], "minimum": 1},
                                   "name": {"type": "string", "minLength": 1, "maxLength": 200}}}
_chunk_schema["properties"].update({
    "content_kind": {"type": "string", "enum": [kind.value for kind in ContentKind]},
    "relations": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False, "required": ["origin", "destination", "conditions"],
        "properties": {"origin": _endpoint_schema, "destination": _endpoint_schema,
            "conditions": {"type": "array", "maxItems": 8, "items": {
                "type": "object", "additionalProperties": False, "required": ["kind", "quote"],
                "properties": {"kind": {"type": "string", "enum": [kind.value for kind in MovementCondition]},
                               "quote": {"type": "string", "minLength": 1, "maxLength": 800}}}}}}},
})


SCHEMA_V7 = deepcopy(SCHEMA_V6)
_relation_schema = SCHEMA_V7["properties"]["chunks"]["items"]["properties"]["relations"]["items"]
_relation_schema["required"] += ["type", "importance", "evidence"]
_relation_schema["properties"].update({
    "type": {"type": "string", "enum": [kind.value for kind in RelationType]},
    "importance": {"type": "string", "enum": [importance.value for importance in RelationImportance]},
    "evidence": {"type": "object", "additionalProperties": False, "required": ["start", "end", "quote"],
                 "properties": {"start": {"type": "integer", "minimum": 0},
                                "end": {"type": "integer", "minimum": 1},
                                "quote": {"type": "string", "minLength": 1, "maxLength": 800}}},
})


def schema_for_prompt(prompt_version: str) -> dict[str, Any]:
    prompt = resolve_prompt(prompt_version)
    if prompt.independent_relations:
        return deepcopy(SCHEMA_V7)
    return deepcopy(SCHEMA_V6) if prompt.supports_relations else SCHEMA


def validate_observation(
    chunk: dict[str, Any],
    places: list[ExistingPlace],
    source: SourceDocument,
    *,
    allow_unresolved: bool = False,
    independent: bool = False,
) -> None:
    kind = ContentKind(chunk["content_kind"])
    relations = chunk["relations"]
    if independent:
        validate_independent_relations(relations, chunk["place_refs"], source.text, chunk["start"], chunk["end"])
    if not independent and kind != ContentKind.MOVEMENT and relations:
        raise ValueError("이동 종류와 출발지·도착지 관계가 일치해야 합니다")
    if kind == ContentKind.MOVEMENT and not relations:
        if allow_unresolved:
            return
        raise ValueError("이동의 출발지·도착지 관계가 없습니다")
    known = {place.place_id: place.name for place in places}
    endpoints = set()
    for relation in relations:
        for endpoint in (relation["origin"], relation["destination"]):
            identifier = endpoint["place_id"]
            if identifier is not None:
                if identifier not in known or known[identifier] != endpoint["name"]:
                    raise ValueError("이동 장소 ID·이름은 등록된 장소와 일치해야 합니다")
                endpoints.add(identifier)
        for condition in relation["conditions"]:
            if condition["quote"] not in source.text[chunk["start"]:chunk["end"]]:
                raise ValueError("이동 조건은 현재 구간 원문에 있어야 합니다")
    if kind == ContentKind.MOVEMENT and not independent:
        subjects = {ref["place_id"] for ref in chunk["place_refs"] if ref["role"] == PlaceRole.SUBJECT}
        if subjects != endpoints:
            raise ValueError("이동 청크의 알려진 출발지·도착지는 핵심 장소로 보존해야 합니다")


def observation_error(
    chunk: dict[str, Any],
    places: list[ExistingPlace],
    source: SourceDocument,
    *,
    independent: bool = False,
) -> str | None:
    try:
        known = {place.place_id for place in places}
        if any(ref["place_id"] not in known for ref in chunk["place_refs"] + chunk["entities"]):
            raise ValueError("미등록 장소 ID")
        if len({ref["place_id"] for ref in chunk["place_refs"]}) != len(chunk["place_refs"]):
            raise ValueError("중복 장소 귀속")
        if not chunk["context_text"].strip() or chunk["hypothetical_questions"]:
            raise ValueError("빈 문맥 또는 허용하지 않은 질문 확장")
        if not chunk["place_refs"] and chunk["entities"]:
            raise ValueError("귀속을 보류한 구간의 엔티티도 비워야 합니다")
        for entity in chunk["entities"]:
            if {"place_id": entity["place_id"], "role": entity["role"]} not in chunk["place_refs"]:
                raise ValueError("엔티티 역할과 장소 귀속 불일치")
        validate_observation(chunk, places, source, allow_unresolved=True, independent=independent)
    except ValueError as exception:
        return str(exception)
    return None


def request_payload(
    places: list[ExistingPlace],
    sources: list[SourceDocument],
    settings: AgentSettings,
    *,
    prompt_version: str = PROMPT_VERSION,
    input_version: str = InputVersion.OFFSETS,
    splitter_version: str = SPLITTER_VERSION,
) -> dict[str, Any]:
    prompt = resolve_prompt(prompt_version)
    splitter_version = SplitterVersion(splitter_version)
    if prompt.supports_relations and splitter_version != SplitterVersion.SENTENCE:
        raise ValueError("관찰·이동 관계 계약에는 문장·문단 분할이 필요합니다")
    if splitter_version != SplitterVersion.LEGACY and InputVersion(input_version) != InputVersion.EXPLICIT:
        raise ValueError("새 분할에는 코드가 추출한 명시적 청크 입력이 필요합니다")
    if prompt.requires_explicit_chunks and InputVersion(input_version) != InputVersion.EXPLICIT:
        raise ValueError("이 프롬프트는 source-explicit-chunks-v2 입력이 필요합니다")
    proposed = [{"source_id": source.source_id, "start": start, "end": end}
                for source in sources for start, end in split_source(source, splitter_version=splitter_version)]
    document = {"places": [place.to_dict() for place in places],
                "sources": [source.to_dict() for source in sources], "spans": proposed}
    if splitter_version != SplitterVersion.LEGACY:
        document["splitter_version"] = splitter_version.value
    if InputVersion(input_version) == InputVersion.EXPLICIT:
        document = explicit_chunks(document)
    return {
        **({"preset": settings.preset} if settings.preset else {"model": settings.model}),
        **({"effort": "fast", "max_output_tokens": 8192} if prompt.supports_relations else {}),
        "instructions": prompt.instructions, "background": False, "tools": [],
        "input": json.dumps(document, ensure_ascii=False),
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "contextualchunks", "strict": True, "schema": schema_for_prompt(prompt_version)}},
    }


def parse_chunks(
    raw: dict[str, Any],
    places: list[ExistingPlace],
    sources: list[SourceDocument],
    *,
    prompt_version: str = PROMPT_VERSION,
    response_schema: dict[str, Any] | None = None,
    request_profile_id: str | None = None,
    validation_version: str | None = None,
    splitter_version: str = SPLITTER_VERSION,
) -> list[SearchChunk]:
    prompt = resolve_prompt(prompt_version)
    validation = resolve_validation_version(validation_version, prompt_version)
    if prompt.supports_relations and SplitterVersion(splitter_version) != SplitterVersion.SENTENCE:
        raise ValueError("관찰·이동 관계 응답에는 문장·문단 분할 버전이 필요합니다")
    if raw.get("status") != "completed":
        raise ValueError("Incomplete contextual generation")
    text = "".join(part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    document = json.loads(text)
    Draft202012Validator(schema_for_prompt(prompt_version)).validate(document)
    if response_schema is not None:
        Draft202012Validator(response_schema).validate(document)
    expected = {(source.source_id, start, end) for source in sources
                for start, end in split_source(source, splitter_version=splitter_version)}
    actual = [(chunk["source_id"], chunk["start"], chunk["end"]) for chunk in document["chunks"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Agent changed, duplicated or omitted source spans")
    by_id = {source.source_id: source for source in sources}
    known_places = {place.place_id for place in places}
    chunks = []
    ordered = document["chunks"]
    if SplitterVersion(splitter_version) != SplitterVersion.LEGACY:
        source_order = {source.source_id: index for index, source in enumerate(sources)}
        ordered = sorted(ordered, key=lambda chunk: (source_order[chunk["source_id"]], chunk["start"], chunk["end"]))
    for chunk in ordered:
        if validation in (ValidationVersion.OBSERVATIONS, ValidationVersion.RELATIONS):
            if observation_error(chunk, places, by_id[chunk["source_id"]], independent=prompt.independent_relations) is not None:
                continue
            if chunk["content_kind"] == ContentKind.MOVEMENT and not chunk["relations"]:
                continue
        if not prompt.allow_hypothetical_questions and chunk["hypothetical_questions"]:
            raise ValueError("Query expansion is disabled for this prompt version")
        if any(ref["place_id"] not in known_places for ref in chunk["place_refs"] + chunk["entities"]):
            raise ValueError("Agent referenced an unknown place")
        if prompt.supports_relations:
            validate_observation(chunk, places, by_id[chunk["source_id"]], independent=prompt.independent_relations)
        if validation in (ValidationVersion.SUBJECT_ONLY, ValidationVersion.OBSERVATIONS, ValidationVersion.RELATIONS):
            if len({ref["place_id"] for ref in chunk["place_refs"]}) != len(chunk["place_refs"]):
                raise ValueError("Chunk place references must be present and unique")
            if not chunk["context_text"].strip():
                raise ValueError("Chunk context must contain 1..600 characters")
        if not chunk["place_refs"]:
            if (prompt.require_empty_unattributed_entities or validation in (ValidationVersion.SUBJECT_ONLY, ValidationVersion.OBSERVATIONS, ValidationVersion.RELATIONS)) and chunk["entities"]:
                raise ValueError("Unattributed spans require both place_refs and entities to be empty")
            continue
        for entity in chunk["entities"]:
            if {"place_id": entity["place_id"], "role": entity["role"]} not in chunk["place_refs"]:
                raise ValueError("Entity roles must match explicit place references")
        if validation in (ValidationVersion.SUBJECT_ONLY, ValidationVersion.OBSERVATIONS, ValidationVersion.RELATIONS):
            has_relation_target = prompt.independent_relations and bool(endpoint_ids(chunk["relations"]))
            if not has_relation_target and not any(ref["role"] == PlaceRole.SUBJECT for ref in chunk["place_refs"]):
                continue
        chunks.append(SearchChunk(by_id[chunk["source_id"]], chunk["start"], chunk["end"],
                                  chunk["context_text"], chunk["place_refs"],
                                  {"provider": "perplexity", "model": raw.get("model"),
                                   "response_id": raw.get("id"), "prompt_version": prompt.version.value,
                                   **({"request_profile_id": request_profile_id} if request_profile_id else {}),
                                   **({"validation_version": validation_version} if validation_version else {})},
                                  chunk["entities"], chunk["hypothetical_questions"], splitter_version,
                                  chunk.get("content_kind"), chunk.get("relations", [])))
    return chunks


async def generate(client: httpx.AsyncClient, settings: AgentSettings, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.api_key.strip():
        raise ValueError("PERPLEXITY_API_KEY is required for contextual generation")
    response = await client.post(AGENT_ENDPOINT, json=payload,
                                 headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
                                 timeout=settings.timeout_seconds)
    response.raise_for_status()
    return response.json()
