"""합성 응답으로 핵심·보조 관계 계약을 검증한다. HTTP·DB·검색 모델은 실행하지 않는다."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "embedding-server"))
from app.contextual.agent import parse_chunks
from app.contextual.contracts import SplitterVersion
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import normalize_source
from app.contextual.prompts import PromptVersion
from app.contextual.validation import ValidationVersion
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import ExistingPlace


def verify() -> dict[str, Any]:
    text = "A공원은 야경이 아름답고, 관람 후 B공원으로 걸어갈 수 있다."
    quotation = "관람 후 B공원으로 걸어갈 수 있다."
    source = normalize_source({"source_type": "review", "title": "합성 회귀 자료", "text": text,
        "metadata": {"source_url": "https://example.org/supporting-relation", "capture_scope": "full_text"}})
    row = {"source_id": source.source_id, "start": 0, "end": len(text), "context_text": "A의 경관과 관람 후 B로의 이동 가능성이다.",
        "content_kind": "landscape", "place_refs": [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "mentioned"}],
        "entities": [], "hypothetical_questions": [], "relations": [{
            "type": "movement", "importance": "supporting", "origin": {"place_id": 394, "name": "A공원"},
            "destination": {"place_id": 395, "name": "B공원"}, "conditions": [],
            "evidence": {"start": text.index(quotation), "end": len(text), "quote": quotation}}]}
    raw = {"id": "synthetic-only", "model": "mock", "status": "completed", "output": [{"type": "message", "content": [{
        "type": "output_text", "text": json.dumps({"chunks": [row]}, ensure_ascii=False)}]}]}
    chunk, = parse_chunks(raw, [ExistingPlace(394, "A공원"), ExistingPlace(395, "B공원")], [source],
        prompt_version=PromptVersion.V7, validation_version=ValidationVersion.RELATIONS, splitter_version=SplitterVersion.SENTENCE)
    results = []
    for identifier, condition, expected in (
        ("landscape_owner_only", {"content_kinds": ["landscape"]}, [394]),
        ("to_b_returns_a", {"destination_place_id": 395}, [394]),
        ("from_a_returns_b", {"origin_place_id": 394}, [395]),
        ("supporting_is_searchable", {"relation_importance": ["supporting"]}, [394, 395]),
        ("supporting_is_not_primary", {"relation_importance": ["primary"]}, []),
        ("all_movements_include_supporting", {"content_kinds": ["movement"]}, [394, 395]),
    ):
        filtering = ObservationFilter.from_mapping(condition)
        actual = [place_id for place_id in (394, 395) if filtering.matches(place_id, chunk.to_dict())]
        if actual != expected:
            raise ValueError("합성 회귀 사례의 결과가 다릅니다")
        results.append({"id": identifier, "filter": condition, "expected": expected, "actual": actual, "passed": True})
    scoped = ObservationFilter.from_mapping({"origin_place_id": 394}).scope_evidence(395, chunk.to_dict())
    if "야경" in scoped["search_text"] or quotation not in scoped["search_text"]:
        raise ValueError("목적지 이동 근거에 출발지 경관이 섞였습니다")
    return {"fixture_kind": "synthetic-model-response", "prompt_version": PromptVersion.V7.value,
        "validation_version": ValidationVersion.RELATIONS.value, "preserved_chunk_count": 1, "fixture": row,
        "chunk_text": text, "queries": results,
        "active_roles": {"394": chunk.active_role(394), "395": chunk.active_role(395)},
        "destination_relation_search_text": scoped["search_text"], "all_passed": True,
        "api_calls": 0, "database_writes": 0, "database_queries": 0, "model_search_executions": 0,
        "note": "코드 계약의 합성 검사다. Sonar 판정 품질·실제 SQL 적용·검색 성능을 측정하지 않았다."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.resolve().is_relative_to((REPOSITORY / "Evaluation/datasets").resolve()):
        parser.error("동결 데이터셋에 쓰지 않습니다")
    write_json(args.output, verify())
    print(args.output)


if __name__ == "__main__":
    main()
