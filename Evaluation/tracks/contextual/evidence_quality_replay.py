"""과거 이동 전용 정책을 오프라인 재생한다. 현재 서비스 경로의 검증 명령이 아니다."""
from __future__ import annotations

import argparse
import ast
from enum import StrEnum
import hashlib
import json
from pathlib import Path, PureWindowsPath
import sys
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT), str(ROOT / "embedding-server")]
from app.contextual.artifacts import load_record
from app.contextual.contracts import SearchChunk, SplitterVersion
from Evaluation.tracks.contextual.experiments.connection_quality.evidence_quality import ContextCoverage, EvidenceContext, apply_connection_quality, question_requirement
from app.contextual.observation_search import ObservationFilter
from app.contextual.review import reviewed_chunks
from app.contextual.pipeline import normalize_source
from app.enrichment.contracts import ExistingPlace
from Evaluation.common.metrics.ranking import ranking_metrics


class ExperimentalPolicy(StrEnum):
    MOVEMENT_REGEX = "movement-regex-v1"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def archived_path(path: str, root: Path) -> Path:
    prefix = PureWindowsPath("C:/ssafy/Travelmate/Evaluation/runs/contextual")
    return root / Path(*PureWindowsPath(path).relative_to(prefix).parts)


def active_documents(root: Path, selections: dict[str, list[str]]) -> dict[int, EvidenceContext]:
    previous = root / "v7-integration-v1/20261101-01"
    summary = json.loads((previous / "sonar/generation-summary.json").read_text(encoding="utf-8"))
    actual = next(case for case in summary["results"] if case["id"] == "P09")
    chunks = reviewed_chunks(archived_path(actual["record"], root), previous / "approval-P09.json")
    processed = root / "v8-server-evidence-v1/20261101-01"
    revalidation = json.loads((processed / "revalidation.json").read_text(encoding="utf-8"))
    control = next(case for case in revalidation["results"] if case["id"] == "CONTROL")
    _, controls, _ = load_record(archived_path(control["processed_record"], root))
    fixture_path = ROOT / "Evaluation/tracks/contextual/v7_search.py"
    provenance = json.loads((ROOT / "Evaluation/runs/contextual/connection-result-audit-v1/20261101-01/provenance.json").read_text(encoding="utf-8"))
    if sha256(fixture_path) != provenance["fixture_code_sha256"]:
        raise ValueError("고정 fixture 코드가 판정 당시와 다릅니다")
    syntax = ast.parse(fixture_path.read_text(encoding="utf-8"))
    function = next(node for node in syntax.body if isinstance(node, ast.FunctionDef) and node.name == "distractors")
    namespace = {"SearchChunk": SearchChunk, "SplitterVersion": SplitterVersion, "normalize_source": normalize_source, "ExistingPlace": ExistingPlace}
    exec(compile(ast.Module(body=[function], type_ignores=[]), "<preserved-fixture>", "exec"), namespace)
    _, fixtures = namespace[function.name]()
    catalogue = {chunk.chunk_id: chunk for chunk in [*chunks, *controls, *fixtures]}
    return {
        int(place_id): EvidenceContext(
            documents=tuple({**catalogue[identifier].to_dict(), "context_version": catalogue[identifier].context_version,
                             "metadata": catalogue[identifier].source.metadata} for identifier in identifiers),
            coverage=ContextCoverage.ACTIVE,
        )
        for place_id, identifiers in selections.items()
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--experimental-policy", type=ExperimentalPolicy, choices=list(ExperimentalPolicy), required=True)
    args = parser.parse_args()
    original = args.archive_root / "general-relation-retrieval-v1/20261101-01"
    manifest = json.loads((ROOT / "Evaluation/runs/contextual/general-relation-retrieval-v1/20261101-01/publication.json").read_text(encoding="utf-8"))
    preserved = {name: sha256(original / name) for name in ("comparison.json", "comparison-plan.json")}
    if any(digest != manifest["local_file_sha256"][name] for name, digest in preserved.items()):
        raise ValueError("보존 결과 해시가 다릅니다")
    comparison = json.loads((original / "comparison.json").read_text(encoding="utf-8"))
    plan = json.loads((original / "comparison-plan.json").read_text(encoding="utf-8"))
    questions = {question["id"]: question for question in plan["questions"]}
    contexts = active_documents(args.archive_root, plan["selected_chunk_ids"])
    audit = ROOT / "Evaluation/runs/contextual/connection-result-audit-v1/20261101-01"
    qrels = {int(identifier): grade for identifier, grade in json.loads((audit / "metrics.json").read_text(encoding="utf-8"))["pool_qrels"].items()}
    judged_chunks = {entry["chunk_id"]: entry["grade"] for entry in json.loads((audit / "judgments.json").read_text(encoding="utf-8"))}
    results = []
    for case in comparison["results"]:
        question = questions[case["id"]]
        ranked = []
        for row in case["ranked_places"]:
            candidate = {**row, "evidence": row["evidence"], "description": row["text"], "source_version": 1}
            for document in row["reranked_evidence_chunks"]:
                if not any(document["chunk_id"] == active["chunk_id"] and document["context_version"] == active["context_version"]
                           for active in contexts[row["place_id"]].documents):
                    raise ValueError("선택 근거가 동결된 활성 목록에 없습니다")
            ranked.append((candidate, row["score"]))
        requirement = question_requirement(question["query"], ObservationFilter.from_mapping(question["filters"].get("observation")))
        batch = apply_connection_quality(ranked, requirement, contexts)
        retained_ids = [row["place_id"] for row, _ in batch.accepted]
        original_ids = [row["place_id"] for row, _ in ranked]
        if retained_ids != [place_id for place_id in original_ids if place_id in set(retained_ids)]:
            raise ValueError("보류하지 않은 장소들의 상대 순서가 바뀌었습니다")
        result = {
            "phase": case["phase"],
            "id": case["id"],
            "quality_scope": requirement.scope,
            "original_count": len(ranked),
            "retained_count": len(batch.accepted),
            "held_count": len(batch.withheld),
            "original_top_20": original_ids[:20],
            "retained_top_20": retained_ids[:20],
            "relative_order_preserved": True,
            "scores_preserved": all(score == dict((row["place_id"], saved_score) for row, saved_score in ranked)[row["place_id"]] for row, score in batch.accepted),
            "retained": [
                {"place_id": row["place_id"], "ranking_score": score,
                 "representative_chunk_id": row["evidence"]["chunk_id"],
                 **({"description": row["description"], "assessment": row["evidence_assessment"]} if "evidence_assessment" in row else {})}
                for row, score in batch.accepted
            ],
            "withheld": [{key: value for key, value in row.items() if key != "evidence_chunks"} for row in batch.withheld],
        }
        if case["id"] == "unnamed-connection":
            result["place_relevance_before"] = ranking_metrics(original_ids, qrels)
            result["place_relevance_after"] = ranking_metrics(retained_ids, qrels)
            result["place_relevant_before"] = sum(qrels.get(identifier, 0) >= 2 for identifier in original_ids)
            result["place_relevant_after"] = sum(qrels.get(identifier, 0) >= 2 for identifier in retained_ids)
            result["precision_at_20_before"] = sum(qrels.get(identifier, 0) >= 2 for identifier in original_ids[:20]) / 20
            result["precision_at_20_after"] = sum(qrels.get(identifier, 0) >= 2 for identifier in retained_ids[:20]) / 20
            result["representative_supported_before"] = sum(judged_chunks[row["evidence"]["chunk_id"]] >= 2 for row, _ in ranked)
            result["representative_supported_after"] = sum(judged_chunks[row["evidence"]["chunk_id"]] >= 2 for row, _ in batch.accepted)
            result["original_top_20_unchanged"] = original_ids[:20] == retained_ids[:20]
        results.append(result)
    if any(sha256(original / name) != digest for name, digest in preserved.items()):
        raise ValueError("재생 중 원본 결과가 변경됐습니다")
    write_json(args.output / "replay.json", {"results": results, "experimental_policy": args.experimental_policy,
        "service_policy": False, "new_searches": 0, "new_model_calls": 0,
        "production_database_writes": 0, "input_sha256": preserved,
        "active_limit": 20, "candidate_limit": 30, "default_search_settings_changed": False})
    print(json.dumps([{key: value for key, value in result.items() if key not in ("retained", "withheld", "place_relevance_before", "place_relevance_after", "original_top_20", "retained_top_20")} for result in results], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
