"""보존된 v7 두 요청을 무료 재처리하고 원본 해시·실패 사례 위치를 검증한다."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "embedding-server"))
from app.contextual.artifacts import load_record, revalidate_record
from app.contextual.evidence_grounding import GroundingVersion
from app.contextual.validation import ValidationVersion
from app.enrichment.artifacts import write_json


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_preserved(root: Path, manifest: dict[str, Any]) -> None:
    for name, expected in manifest["local_file_sha256"].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root.resolve()) or sha256(path) != expected:
            raise ValueError("기존 공개 명세와 보존 파일 해시가 다릅니다")


def execute(archive_root: Path, output: Path) -> Path:
    if output.exists():
        raise ValueError("재처리 출력은 새 폴더여야 합니다")
    manifest_path = archive_root / "publication.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest_sha256 = sha256(manifest_path)
    verify_preserved(archive_root, manifest)
    records = sorted((archive_root / name).resolve() for name in manifest["paid_archive_file_sha256"] if name.endswith("/record.json"))
    if len(records) != 2:
        raise ValueError("검증 대상은 보존된 CONTROL/P09 두 요청이어야 합니다")
    expectations = {"CONTROL": {"quote": "관람 후 B공원으로 걸어갈 수 있다.", "span": {"start": 15, "end": 35}},
                    "P09": {"quote": "이제부터 계단으로 올라가시면 돼요", "span": {"start": 264, "end": 282}}}
    results = []
    output.mkdir(parents=True)
    with patch("httpx.AsyncClient", side_effect=AssertionError("무료 재검증에는 HTTP 클라이언트가 필요하지 않습니다")):
        for source in records:
            if not source.is_relative_to(archive_root.resolve()):
                raise ValueError("원본 아카이브 범위를 벗어난 경로")
            bundle, original_chunks, _ = load_record(source)
            identifier = "CONTROL" if len(bundle.places) == 2 else "P09"
            expected = expectations[identifier]
            result_path = revalidate_record(source, output / "records", validation_version=ValidationVersion.SERVER_EVIDENCE)
            _, chunks, record = load_record(result_path)
            audits = [entry for entry in record["evidence_grounding"] if entry["quote"] == expected["quote"]]
            if len(audits) != 1 or audits[0]["server_span"] != expected["span"]:
                raise ValueError("고정 회귀 인용 위치 불일치")
            target = audits[0]
            retained = any(chunk.source.source_id == target["source_id"] and chunk.start == target["chunk_span"]["start"]
                           and chunk.end == target["chunk_span"]["end"] for chunk in chunks)
            if not retained:
                raise ValueError("고정 회귀 인용의 부모 청크가 여전히 제외됩니다")
            before_ids = {chunk.chunk_id for chunk in original_chunks}
            originals = {name: sha256(source.with_name(name)) for name in ("record.json", "request.json", "sources.json", "raw_response.json")}
            for name in ("request.json", "sources.json", "raw_response.json"):
                if sha256(result_path.with_name(name)) != originals[name]:
                    raise ValueError("재처리가 원본 요청·응답·원문을 변경했습니다")
            results.append({"id": identifier, "source_record": str(source), "processed_record": str(result_path),
                            "original_file_sha256": originals, "processed_record_sha256": sha256(result_path),
                            "old_candidates": len(original_chunks), "new_candidates": len(chunks),
                            "newly_retained": sum(chunk.chunk_id not in before_ids for chunk in chunks),
                            "excluded": len(record["excluded_chunks"]),
                            "exclusion_errors": dict(Counter(row.get("validation_error", row["exclusion_reason"]) for row in record["excluded_chunks"])),
                            "regression_case": {"chunk_span": target["chunk_span"], "quote": target["quote"],
                                                "model_evidence": target["model_evidence"], "server_span": target["server_span"],
                                                "parent_retained": retained}})
    verify_preserved(archive_root, manifest)
    if sha256(manifest_path) != manifest_sha256:
        raise ValueError("기존 보존 명세가 변경됐습니다")
    report = {"validation_version": ValidationVersion.SERVER_EVIDENCE.value,
              "evidence_grounding_version": GroundingVersion.EXACT_UNIQUE.value,
              "source_publication_sha256": manifest_sha256,
              "preserved_files_verified": len(manifest["local_file_sha256"]), "results": results,
              "api_calls": 0, "production_database_writes": 0, "search_executions": 0,
              "semantic_quality_evaluated": False, "new_prompt_generation_evaluated": False,
              "note": "동일한 저장 응답에 서버 규칙만 변경해 적용했다. 새 모델 판정·검색 개선을 의미하지 않는다."}
    path = output / "revalidation.json"
    write_json(path, report)
    return path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = execute(args.archive_root, args.output)
    report = json.loads(result.read_text(encoding="utf-8"))
    print(json.dumps({"report": str(result), "api_calls": 0, "preserved_files_verified": report["preserved_files_verified"],
                      "results": [{key: row[key] for key in ("id", "old_candidates", "new_candidates", "newly_retained", "excluded")} for row in report["results"]]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
