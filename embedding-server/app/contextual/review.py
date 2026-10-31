"""새 관찰 청크는 원문·응답에 묶인 검수 목록을 거쳐 적용한다."""
from __future__ import annotations

from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any

from .artifacts import load_record
from .contracts import SearchChunk, SplitterVersion, SPLITTER_VERSION, PlaceRole
from .pipeline import select_active
from .prompts import resolve_prompt


class ReviewVersion(StrEnum):
    V1 = "contextual-approval-v1"


class SelectionReason(StrEnum):
    NOT_APPROVED = "not_approved"
    DUPLICATE = "duplicate"
    LIMIT = "limit_20"


def file_hashes(path: Path) -> dict[str, str]:
    return {name: hashlib.sha256(path.with_name(name).read_bytes()).hexdigest()
            for name in ("record.json", "request.json", "sources.json", "raw_response.json")}


def approval_document(path: Path, identifiers: list[str], reviewer: str) -> dict[str, Any]:
    _, chunks, record = load_record(path)
    known = {chunk.chunk_id for chunk in chunks}
    if not reviewer.strip() or len(set(identifiers)) != len(identifiers) or not set(identifiers).issubset(known):
        raise ValueError("검수자와 중복 없는 유효 검색 후보 ID가 필요합니다")
    return {"review_version": ReviewVersion.V1.value, "request_hash": record["request_hash"],
            "file_sha256": file_hashes(path), "reviewer": reviewer, "approved_chunk_ids": identifiers}


def reviewed_chunks(path: Path, review_path: Path | None) -> list[SearchChunk]:
    _, chunks, record = load_record(path)
    required = (record.get("splitter_version", SPLITTER_VERSION) != SplitterVersion.LEGACY
                or resolve_prompt(record["prompt_version"]).supports_relations)
    if not required and review_path is None:
        return chunks
    if not chunks and review_path is None:
        return []
    if review_path is None:
        raise ValueError("새 분할·관계 청크의 DB 적용에는 검수 목록이 필요합니다")
    review = json.loads(review_path.read_text(encoding="utf-8"))
    expected = approval_document(path, review["approved_chunk_ids"], review["reviewer"])
    if review != expected:
        raise ValueError("검수 목록의 원문·응답·버전 또는 승인 내용이 다릅니다")
    approved = set(review["approved_chunk_ids"])
    return [chunk for chunk in chunks if chunk.chunk_id in approved]


def selection_report(path: Path, review_path: Path) -> dict[str, Any]:
    bundle, all_chunks, record = load_record(path)
    approved = reviewed_chunks(path, review_path)
    approved_ids = {chunk.chunk_id for chunk in approved}
    places = []
    for place in bundle.places:
        candidates = [chunk for chunk in all_chunks if any(
            ref["place_id"] == place.place_id and ref["role"] == PlaceRole.SUBJECT for ref in chunk.place_refs)]
        active = select_active(place.place_id, approved)
        selected_ids = {chunk.chunk_id for chunk in active}
        selected_texts = {" ".join(chunk.chunk_text.split()) for chunk in active}
        omitted = []
        for chunk in candidates:
            if chunk.chunk_id in selected_ids:
                continue
            reason = (SelectionReason.NOT_APPROVED if chunk.chunk_id not in approved_ids else
                      SelectionReason.DUPLICATE if " ".join(chunk.chunk_text.split()) in selected_texts else SelectionReason.LIMIT)
            omitted.append({"chunk_id": chunk.chunk_id, "reason": reason})
        places.append({"place_id": place.place_id, "approved": sum(chunk.chunk_id in approved_ids for chunk in candidates),
                       "selected_chunk_ids": [chunk.chunk_id for chunk in active], "omitted": omitted})
    return {"request_hash": record["request_hash"], "places": places, "database_writes": 0}
