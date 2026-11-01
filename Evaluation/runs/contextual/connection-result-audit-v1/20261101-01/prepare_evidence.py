"""저장 결과의 원문을 검증해 오프라인 의미 검수용 패킷을 만든다."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(ROOT / "embedding-server"))
from app.contextual.contracts import SearchChunk, SourceDocument, SplitterVersion
from app.contextual.pipeline import normalize_source
from app.enrichment.contracts import ExistingPlace


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def fixture_sources(path: Path) -> list[SourceDocument]:
    syntax = ast.parse(path.read_text(encoding="utf-8"))
    function = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == "distractors")
    namespace = {
        "ExistingPlace": ExistingPlace,
        "SearchChunk": SearchChunk,
        "SplitterVersion": SplitterVersion,
        "normalize_source": normalize_source,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(path), "exec"), namespace)
    _, chunks = namespace[function.name]()
    return [chunk.source for chunk in chunks]


def evidence_key(document: dict[str, Any]) -> str:
    return document["chunk_id"] + ":" + document["context_version"]


def packet_for(
    document: dict[str, Any],
    sources: dict[tuple[str, str], SourceDocument],
) -> dict[str, Any]:
    source = sources[(document["source_id"], document["source_version"])]
    chunk = SearchChunk.from_mapping(source, document)
    if chunk.context_version != document["context_version"]:
        raise ValueError("저장 문맥 버전과 원문 재구성 결과가 다릅니다")
    return {
        "evidence_key": evidence_key(document),
        "chunk_id": document["chunk_id"],
        "context_version": document["context_version"],
        "source_id": source.source_id,
        "source_version": source.source_version,
        "source_url": source.metadata["source_url"],
        "source_span": document["source_span"],
        "raw_quote": chunk.chunk_text,
        "context_text": chunk.context_text,
        "place_refs": chunk.place_refs,
        "relations": chunk.relations,
        "generation_provider": chunk.generation["provider"],
        "source_span_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    args = parser.parse_args()
    output = Path(__file__).resolve().parent
    local_run = args.archive_root / "general-relation-retrieval-v1/20261101-01"
    publication = json.loads((ROOT / "Evaluation/runs/contextual/general-relation-retrieval-v1/20261101-01/publication.json").read_text(encoding="utf-8"))
    tracked_inputs = ["comparison.json", "comparison-plan.json"]
    for name in tracked_inputs:
        if sha256(local_run / name) != publication["local_file_sha256"][name]:
            raise ValueError("보존된 실행 결과 해시가 다릅니다")
    bundles = [
        path
        for archive in ("v7-integration-v1/20261101-01/sonar", "v8-server-evidence-v1/20261101-01/records")
        for path in sorted((args.archive_root / archive).rglob("sources.json"))
    ]
    originals = [
        SourceDocument.from_mapping(source)
        for path in bundles
        for source in json.loads(path.read_text(encoding="utf-8"))["sources"]
    ]
    fixture_path = ROOT / "Evaluation/tracks/contextual/v7_search.py"
    sources = {(source.source_id, source.source_version): source for source in originals + fixture_sources(fixture_path)}
    comparison = json.loads((local_run / "comparison.json").read_text(encoding="utf-8"))
    rubric = json.loads((output / "rubric.json").read_text(encoding="utf-8"))
    cases = [case for case in comparison["results"] if case["id"] == rubric["query_id"]]
    if len(cases) != 2:
        raise ValueError("기존·변경 결과가 정확히 두 개여야 합니다")
    packets: dict[str, dict[str, Any]] = {}
    rows = []
    for case in cases:
        for rank, row in enumerate(case["ranked_places"], 1):
            documents = [row["evidence"], *row["reranked_evidence_chunks"]]
            for document in documents:
                key = evidence_key(document)
                packet = packet_for(document, sources)
                if packets.get(key, packet) != packet:
                    raise ValueError("같은 근거 키의 원문·문맥이 다릅니다")
                packets[key] = packet
            representative = row["evidence"]
            expected = representative.get("search_text") or representative["context_text"] + "\n\n" + representative["chunk_text"]
            if row["text"] != expected:
                raise ValueError("대표 description이 저장된 근거 표현과 다릅니다")
            for document in documents:
                matched = document.get("matched_relations", [])
                if any(relation not in document["relations"] for relation in matched):
                    raise ValueError("선택 관계와 보존 원문 관계가 다릅니다")
                if "retrieved_relation_index" in document:
                    selected = document["relations"][document["retrieved_relation_index"]]
                    if matched != [selected]:
                        raise ValueError("선택 순번의 관계만 근거 범위에 있어야 합니다")
                if document.get("retrieval_scope") == "relation":
                    expected = "이동 관계 근거\n" + "\n".join(
                        f"출발지: {relation['origin']['name']} → 도착지: {relation['destination']['name']}\n" + relation["evidence"]["quote"]
                        for relation in matched
                    )
                    if document["search_text"] != expected:
                        raise ValueError("관계 입력이 출발·도착지와 원문 인용을 바꿨습니다")
                if document["relations"] and not any(
                    row["place_id"] in (relation["origin"]["place_id"], relation["destination"]["place_id"])
                    for relation in document["relations"]
                ):
                    raise ValueError("반환 장소가 이동 관계의 참가자가 아닙니다")
            rows.append({
                "phase": case["phase"],
                "rank": rank,
                "place_id": row["place_id"],
                "score": row["score"],
                "representative_evidence_key": evidence_key(representative),
                "representative_path": representative.get("retrieval_path", "chunk"),
                "evidence_keys": list(dict.fromkeys(evidence_key(document) for document in row["reranked_evidence_chunks"])),
                "direction_and_restrictions_preserved": True,
            })
    write_json(output / "evidence-packets.json", list(packets.values()))
    write_json(output / "saved-rows.json", rows)
    write_json(output / "provenance.json", {
        "reviewed_commit": "b35afbab",
        "local_input_sha256": {name: sha256(local_run / name) for name in tracked_inputs},
        "source_bundle_sha256": {str(path.relative_to(args.archive_root)).replace('\\', '/'): sha256(path) for path in bundles},
        "fixture_code_path": str(fixture_path.relative_to(ROOT)).replace('\\', '/'),
        "fixture_code_sha256": sha256(fixture_path),
        "rubric_sha256": sha256(output / "rubric.json"),
        "source_versions_checked": len(sources),
        "unique_reviewed_chunks": len(packets),
        "ranked_rows": len(rows),
        "new_searches": 0,
        "new_model_calls": 0,
        "production_database_writes": 0,
    })
    print(json.dumps({"unique_chunks": len(packets), "rows": len(rows), "place_pool": len({row['place_id'] for row in rows})}))


if __name__ == "__main__":
    main()
