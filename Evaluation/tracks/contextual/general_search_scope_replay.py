"""저장된 리랭킹 결과의 반환 계약만 비교한다. 실제 검색·모델을 실행하지 않는다."""
from __future__ import annotations

import argparse
import ast
from copy import deepcopy
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[3]
RUNTIME = "embedding-server/app/kafka_runtime.py"
BASELINE = "c5d0c7bd"
PREVIOUS = "87e06d3e"
OUTPUT_FIELDS = ("region", "city", "category", "source_category", "latitude", "longitude", "tour_content_id", "image_url", "homepage_url")
PRESERVED_FILES = (
    "embedding-server/app/contextual/contracts.py",
    "embedding-server/app/contextual/evidence_grounding.py",
    "embedding-server/app/contextual/relations.py",
    "embedding-server/app/contextual/pipeline.py",
    "embedding-server/app/contextual/repository.py",
    "embedding-server/app/contextual/ranking.py",
    "embedding-server/app/contextual/retrieval.py",
    "embedding-server/app/contextual/relation_vectors.py",
    "embedding-server/app/contextual/observation_search.py",
)


def sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def git_source(commit: str, path: str) -> str:
    return subprocess.check_output(["git", "show", f"{commit}:{path}"], cwd=ROOT).decode("utf-8")


def runtime_method(source: str, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    syntax = ast.parse(source)
    runtime = next(node for node in syntax.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
    return next(node for node in runtime.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name)


def formatter(source: str) -> Callable[[dict[str, Any], int, float], dict[str, Any]]:
    syntax = ast.parse(source)
    enums = [node for node in syntax.body if isinstance(node, ast.ClassDef) and node.name == "EvidenceAssessmentStatus"]
    selected = runtime_method(source, "_to_result_item")
    selected.decorator_list = []
    from app.contextual.result_mapping import result_item
    namespace = {"Any": Any, "json": json, "StrEnum": StrEnum, "result_item": result_item}
    exec(compile(ast.Module(body=[*enums, selected], type_ignores=[]), "<stored-result-formatter>", "exec"), namespace)
    return namespace[selected.name]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    archive = args.archive_root / "general-relation-retrieval-v1/20261101-01"
    original = archive / "comparison.json"
    plan = archive / "comparison-plan.json"
    input_hashes = {path.name: sha256(path.read_bytes()) for path in (original, plan)}
    publication = ROOT / "Evaluation/runs/contextual/general-relation-retrieval-v1/20261101-01/publication.json"
    expected = json.loads(publication.read_text(encoding="utf-8"))["local_file_sha256"]
    assert all(digest == expected[name] for name, digest in input_hashes.items())
    comparison = json.loads(original.read_text(encoding="utf-8"))
    source = (ROOT / RUNTIME).read_text(encoding="utf-8")
    baseline = git_source(BASELINE, RUNTIME)
    methods = {name: ast.dump(runtime_method(source, name)) == ast.dump(runtime_method(baseline, name))
               for name in ("__init__", "_complete_recommendation", "_retrieve_candidates", "_retrieve_evidence", "_index_place_job")}
    preserved = {path: (ROOT / path).read_text(encoding="utf-8") == git_source(PREVIOUS, path) for path in PRESERVED_FILES}
    assert all(methods.values()) and all(preserved.values())
    old_format, current_format = formatter(baseline), formatter(source)
    previous_path = ROOT / "Evaluation/runs/contextual/evidence-quality-policy-v1/20261101-01/replay.json"
    previous = {(case["phase"], case["id"]): case for case in json.loads(previous_path.read_text(encoding="utf-8"))["results"]}
    cases = []
    for case in comparison["results"]:
        evidence_count = 0
        descriptions_unchanged = True
        evidence_unchanged = True
        for rank, saved in enumerate(case["ranked_places"], 1):
            candidate = {**deepcopy(saved), **dict.fromkeys(OUTPUT_FIELDS), "name": str(saved["place_id"]),
                         "description": saved["text"], "source_version": 1, "latest_seen_version": 1, "semantic_score": 0.0}
            before = old_format(candidate, rank, saved["score"])
            after = current_format(candidate, rank, saved["score"])
            assessment = after.pop("evidence_assessment")
            assert assessment == {"status": "not_assessed"}
            assert before == after
            descriptions_unchanged &= after["description"] == saved["text"]
            evidence_unchanged &= after["evidence_chunks"] == saved["reranked_evidence_chunks"]
            evidence_count += len(after["evidence_chunks"])
        prior = previous[(case["phase"], case["id"])]
        identifiers = [row["place_id"] for row in case["ranked_places"]]
        current = {
            "phase": case["phase"], "id": case["id"], "full_ranked_count": len(identifiers),
            "current_top_20": identifiers[:20], "pre_policy_top_20_equal": True,
            "same_full_order_scores_and_evidence_as_pre_policy": True,
            "descriptions_unchanged": descriptions_unchanged, "selected_documents_unchanged": evidence_unchanged,
            "selected_document_count": evidence_count, "semantic_status": "not_assessed",
            "previous_policy_retained_count": prior["retained_count"],
            "previous_policy_held_count": prior["held_count"],
            "top_20_equal_to_previous_policy": identifiers[:20] == prior["retained_top_20"],
        }
        cases.append(current)
    assert len(cases) == 18
    assert input_hashes == {path.name: sha256(path.read_bytes()) for path in (original, plan)}
    application = ROOT / "embedding-server/app"
    policy_imports = [str(path.relative_to(ROOT)) for path in application.rglob("*.py")
                      if any(isinstance(node, ast.ImportFrom) and node.module and
                             any(part in node.module.split(".") for part in ("connection_quality", "connection_statements", "evidence_quality", "experiments"))
                             for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))))]
    assert not policy_imports
    output = {"results": cases, "comparison_boundary": "saved ranked rows -> actual result formatter; full ranking method AST matches pre-policy",
              "pre_policy_commit": BASELINE, "previous_policy_commit": PREVIOUS, "input_sha256": input_hashes,
              "unchanged_method_ast": methods, "preserved_files": preserved, "application_policy_imports": policy_imports,
              "new_real_searches": 0, "new_real_model_calls": 0, "production_database_writes": 0}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "replay.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"cases": len(cases), "preserved_methods": methods, "preserved_files": len(preserved),
                      "application_policy_imports": policy_imports, "new_real_searches": 0}))


if __name__ == "__main__":
    main()
