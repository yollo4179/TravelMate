"""Check exact quotes against provider tool excerpts; this is not full-page verification."""
from __future__ import annotations

import json
from typing import Any
from urllib.parse import urlsplit

from jsonschema import Draft202012Validator

from .contracts import ENRICHMENT_SCHEMA, EntityMatch, EvidenceStatus, ExistingPlace


def source_url(value: Any) -> str:
    if not isinstance(value, str):
        raise ValueError("Source URL must be a string")
    parsed = urlsplit(value)
    if parsed.scheme not in ("https", "http") or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Source URL must be an HTTP(S) URL without credentials")
    return value


def extract_document(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("status") != "completed":
        raise ValueError("Agent response is incomplete or failed; no indexing allowed")
    texts = [
        part["text"]
        for item in raw.get("output", []) if item.get("type") == "message"
        for part in item.get("content", []) if part.get("type") == "output_text" and isinstance(part.get("text"), str)
    ]
    document = json.loads("".join(texts))
    Draft202012Validator(ENRICHMENT_SCHEMA).validate(document)
    return document


def extract_sources(raw: dict[str, Any]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    for item in raw.get("output", []):
        if item.get("type") == "search_results":
            rows = item.get("results", [])
        elif item.get("type") == "fetch_url_results":
            rows = item.get("contents", [])
        else:
            continue
        for row in rows:
            try:
                url = source_url(row.get("url"))
            except ValueError:
                continue
            sources.append({
                "url": url, "title": row.get("title"), "snippet": row.get("snippet") or "",
                "published_at": row.get("date") or row.get("published_at"),
                "tool_type": item["type"],
            })
    return sources


def normalize_response(place: ExistingPlace, raw: dict[str, Any]) -> dict[str, Any]:
    document = extract_document(raw)
    if document["place_id"] != place.place_id:
        raise ValueError("Agent returned a different place ID")
    sources = extract_sources(raw)
    conflict_aspects = {conflict["aspect"] for conflict in document["conflicts"]}
    normalized_claims = []
    for claim in document["claims"]:
        verified = []
        for evidence in claim["evidence"]:
            url = source_url(evidence["url"])
            quote = " ".join(evidence["quote"].split())
            matches = any(
                source["url"] == url and quote and quote in " ".join(source["snippet"].split())
                for source in sources
            )
            verified.append({**evidence, "status": EvidenceStatus.EXCERPT_MATCHED.value if matches else EvidenceStatus.UNVERIFIED.value})
        searchable = (
            document["entity_match"] == EntityMatch.MATCHED
            and claim["aspect"] not in conflict_aspects
            and any(item["status"] == EvidenceStatus.EXCERPT_MATCHED for item in verified)
        )
        normalized_claims.append({**claim, "evidence": verified, "searchable": searchable})
    return {**document, "claims": normalized_claims, "sources": sources,
            "verification_scope": "Exact whitespace-normalized quote match in provider-returned tool excerpts, not an independent fetch or fact check"}


def searchable_claims(document: dict[str, Any]) -> list[dict[str, Any]]:
    return [claim for claim in document["claims"] if claim["searchable"]]


def search_description(place: ExistingPlace, document: dict[str, Any]) -> str:
    lines = [place.description or ""]
    for claim in searchable_claims(document):
        evidence = next(item for item in claim["evidence"] if item["status"] == EvidenceStatus.EXCERPT_MATCHED)
        condition = " / ".join(claim["conditions"])
        lines.append(f"[웹 자료의 관찰·후기, 현재 사실 여부는 별도 확인] {claim['aspect']}: {claim['statement']}"
                     + (f" (조건: {condition})" if condition else "")
                     + f" 근거: {evidence['quote']} 출처: {evidence['url']}")
    return "\n".join(line for line in lines if line)
