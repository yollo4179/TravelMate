"""현재 도구 경로와 평가 파일의 연결 상태를 읽기 전용으로 기록한다."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
SERVER = "Server/TravelMate/src/main/java/com/yollo/TravelMate/"
SOURCE_FILES = (
    SERVER + "ai/llm/base/LlmClient.java",
    SERVER + "ai/llm/derived/OllamaLlmClient.java",
    SERVER + "domain/place/client/PlaceSemanticSearchClient.java",
    SERVER + "domain/place/data/result/PlaceSemanticSearchResult.java",
    SERVER + "domain/place/data/response/PlaceSearchResponseDto.java",
    SERVER + "domain/place/controller/PlaceSearchController.java",
    SERVER + "domain/place/service/PlaceSemanticSearchService.java",
    SERVER + "domain/plan/controller/ContextPlanningController.java",
    SERVER + "domain/plan/service/ContextPlanningService.java",
    SERVER + "domain/plan/service/PlanGenerationService.java",
    SERVER + "domain/plan/data/request/GeneratePlanRequest.java",
    SERVER + "domain/plan/data/request/PlanContext.java",
    SERVER + "domain/plan/data/response/PlanningResponse.java",
    SERVER + "domain/plan/validator/ContextPlanResultValidator.java",
    SERVER + "domain/plan/prompts/ContextPlanPromptFactory.java",
    SERVER + "domain/plan/repository/ContextPlanRepository.java",
    SERVER + "domain/plan/repository/PlanRepository.java",
    "embedding-server/app/kafka_runtime.py",
    "Evaluation/common/paths.py",
    "Evaluation/common/dataset/contracts.py",
    "Evaluation/common/runs/runner.py",
    "Evaluation/tracks/end_to_end/score.py",
    "Evaluation/tracks/tool_call/score_args.py",
    "Evaluation/tracks/search/score_ranking.py",
    "Evaluation/tracks/plan/score_rules.py",
    "Evaluation/tracks/state/score.py",
    "Evaluation/datasets/v1.4.0/generated/schemas/tool_contracts.json",
    "Evaluation/datasets/v1.4.0/generated/schemas/response_record.schema.json",
    "Evaluation/datasets/v1.4.0/manifest.json",
    "Evaluation/datasets/v1.4.0/generated/golden.jsonl",
    "Evaluation/tracks/contextual/pilot_cases.json",
)
LOCAL_SEARCH_FILES = (
    "Evaluation/tracks/search/collect_live.py",
    "Evaluation/tracks/search/collect_holdout.py",
    "Evaluation/tracks/search/holdout.py",
    "Evaluation/tracks/search/compare_holdout.py",
    "Evaluation/tracks/search/judge_candidates.py",
    "Evaluation/tracks/search/audit_candidate_conditions.py",
)


def snapshot(root: Path, path: str) -> dict[str, Any]:
    target = root / path
    if not target.is_file():
        return {"exists": False}
    content = target.read_bytes()
    return {
        "exists": True,
        "raw_sha256": hashlib.sha256(content).hexdigest(),
        "lf_sha256": hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest(),
        "git_status": subprocess.check_output(["git", "status", "--short", "--", path], cwd=root).decode("utf-8").strip(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--local-workspace", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    dataset = ROOT / "Evaluation/datasets/v1.4.0"
    cases = [json.loads(line) for line in (dataset / "generated/golden.jsonl").read_text(encoding="utf-8").splitlines() if line]
    tool_contract = json.loads((dataset / "generated/schemas/tool_contracts.json").read_text(encoding="utf-8"))
    pilot = json.loads((ROOT / "Evaluation/tracks/contextual/pilot_cases.json").read_text(encoding="utf-8"))
    tracked = {path: snapshot(ROOT, path) for path in SOURCE_FILES}
    local = {path: snapshot(args.local_workspace, path) for path in (*SOURCE_FILES, *LOCAL_SEARCH_FILES)} if args.local_workspace else {}
    local_differences = {
        path: {**entry, "same_as_audited_branch": entry.get("lf_sha256") == tracked.get(path, {}).get("lf_sha256")}
        for path, entry in local.items()
        if entry["exists"] and (entry["git_status"] or path not in tracked)
    }
    report = {
        "audit_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT).decode().strip(),
        "audit_type": "static_source_and_contract_inventory; not a quality evaluation",
        "dataset": {
            "version": "v1.4.0", "declared_case_count": len(cases),
            "track_membership_counts": dict(Counter(track for case in cases for track in case["evaluation_tracks"])),
            "response_type_counts": dict(Counter(case["expected_response_type"] for case in cases)),
            "required_tool_call_instances": dict(Counter(call["name"] for case in cases for call in case["expectations"]["tool_call"]["required_calls"])),
            "cases_with_route_fixture": sum(bool(case["fixtures"].get("travel_cost_matrix")) for case in cases),
            "corpus_place_count": len(json.loads((dataset / "generated/corpus.json").read_text(encoding="utf-8"))),
            "tool_contract_implementation_status": tool_contract["implementation_status"],
            "tool_contracts": tool_contract["tools"],
        },
        "contextual_pilot": {"query_count": len(pilot["queries"]), "source": "Evaluation/tracks/contextual/pilot_cases.json", "held_out": False},
        "audited_branch_files": tracked,
        "local_workspace_differences_not_committed_with_audit": local_differences,
        "executed_quality_evaluation_cases": 0, "new_evaluation_cases": 0,
        "real_model_calls": 0, "live_search_calls": 0, "production_database_writes": 0,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8") as destination:
        json.dump(report, destination, ensure_ascii=False, indent=2)
        destination.write("\n")
    print(json.dumps({"declared_cases": len(cases), "source_files": len(tracked),
                      "local_differences": len(local_differences), "executed_quality_evaluation_cases": 0}))


if __name__ == "__main__":
    main()
