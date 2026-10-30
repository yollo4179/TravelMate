"""Agent contextualization of supplied source spans, without replacing quotations."""
from __future__ import annotations

import json
from typing import Any

import httpx
from jsonschema import Draft202012Validator

from app.enrichment.agent import AGENT_ENDPOINT, AgentSettings
from app.enrichment.contracts import ExistingPlace
from .contracts import PlaceRole, SearchChunk, SourceDocument
from .pipeline import split_source
from .prompts import DEFAULT_PROMPT_VERSION, resolve_prompt

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


def request_payload(
    places: list[ExistingPlace],
    sources: list[SourceDocument],
    settings: AgentSettings,
    *,
    prompt_version: str = PROMPT_VERSION,
) -> dict[str, Any]:
    prompt = resolve_prompt(prompt_version)
    proposed = [{"source_id": source.source_id, "start": start, "end": end}
                for source in sources for start, end in split_source(source)]
    return {
        **({"preset": settings.preset} if settings.preset else {"model": settings.model}),
        "instructions": prompt.instructions, "background": False, "tools": [],
        "input": json.dumps({"places": [place.to_dict() for place in places],
                             "sources": [source.to_dict() for source in sources], "spans": proposed}, ensure_ascii=False),
        "response_format": {"type": "json_schema", "json_schema": {
            "name": "contextualchunks", "strict": True, "schema": SCHEMA}},
    }


def parse_chunks(
    raw: dict[str, Any],
    places: list[ExistingPlace],
    sources: list[SourceDocument],
    *,
    prompt_version: str = PROMPT_VERSION,
    response_schema: dict[str, Any] | None = None,
    request_profile_id: str | None = None,
) -> list[SearchChunk]:
    prompt = resolve_prompt(prompt_version)
    if raw.get("status") != "completed":
        raise ValueError("Incomplete contextual generation")
    text = "".join(part["text"] for item in raw.get("output", []) if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    document = json.loads(text)
    Draft202012Validator(SCHEMA).validate(document)
    if response_schema is not None:
        Draft202012Validator(response_schema).validate(document)
    expected = {(source.source_id, start, end) for source in sources for start, end in split_source(source)}
    actual = [(chunk["source_id"], chunk["start"], chunk["end"]) for chunk in document["chunks"]]
    if len(actual) != len(set(actual)) or set(actual) != expected:
        raise ValueError("Agent changed, duplicated or omitted source spans")
    by_id = {source.source_id: source for source in sources}
    known_places = {place.place_id for place in places}
    chunks = []
    for chunk in document["chunks"]:
        if not prompt.allow_hypothetical_questions and chunk["hypothetical_questions"]:
            raise ValueError("Query expansion is disabled for this prompt version")
        if any(ref["place_id"] not in known_places for ref in chunk["place_refs"] + chunk["entities"]):
            raise ValueError("Agent referenced an unknown place")
        if not chunk["place_refs"]:
            if prompt.require_empty_unattributed_entities and chunk["entities"]:
                raise ValueError("Unattributed spans require both place_refs and entities to be empty")
            continue
        for entity in chunk["entities"]:
            if {"place_id": entity["place_id"], "role": entity["role"]} not in chunk["place_refs"]:
                raise ValueError("Entity roles must match explicit place references")
        chunks.append(SearchChunk(by_id[chunk["source_id"]], chunk["start"], chunk["end"],
                                  chunk["context_text"], chunk["place_refs"],
                                  {"provider": "perplexity", "model": raw.get("model"),
                                   "response_id": raw.get("id"), "prompt_version": prompt.version.value,
                                   **({"request_profile_id": request_profile_id} if request_profile_id else {})},
                                  chunk["entities"], chunk["hypothetical_questions"]))
    return chunks


async def generate(client: httpx.AsyncClient, settings: AgentSettings, payload: dict[str, Any]) -> dict[str, Any]:
    if not settings.api_key.strip():
        raise ValueError("PERPLEXITY_API_KEY is required for contextual generation")
    response = await client.post(AGENT_ENDPOINT, json=payload,
                                 headers={"Authorization": f"Bearer {settings.api_key.strip()}"},
                                 timeout=settings.timeout_seconds)
    response.raise_for_status()
    return response.json()
