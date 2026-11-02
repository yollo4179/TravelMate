"""이미 실행한 모의 단위 검증과 변경 범위만 보존한다. 모델·검색을 호출하지 않는다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ElementTree
from typing import Any

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[4]
BASE = "15d3d740"
JAVA = "Server/TravelMate/src/main/java/com/yollo/TravelMate/"
CODE = (
    JAVA + "domain/place/client/PlaceSemanticSearchClient.java",
    JAVA + "domain/place/data/result/SearchEvidenceChunk.java",
    JAVA + "domain/place/data/result/PlaceSemanticSearchResult.java",
    JAVA + "domain/place/data/response/PlaceSearchResponseDto.java",
    JAVA + "domain/plan/data/internal/GeneratedPlan.java",
    JAVA + "domain/plan/prompts/ContextPlanPromptFactory.java",
    JAVA + "domain/plan/service/ContextPlanningService.java",
    JAVA + "domain/plan/validator/PlanEvidenceCitationValidator.java",
    "Server/TravelMate/src/test/java/com/yollo/TravelMate/SearchEvidenceFixtures.java",
    "Server/TravelMate/src/test/java/com/yollo/TravelMate/SearchEvidencePipelineTest.java",
)
UNCHANGED = (
    "embedding-server/app/kafka_runtime.py",
    "embedding-server/app/contextual/contracts.py",
    "embedding-server/app/contextual/pipeline.py",
    "embedding-server/app/contextual/ranking.py",
    "embedding-server/app/contextual/retrieval.py",
    JAVA + "domain/place/service/PlaceSemanticSearchService.java",
    JAVA + "domain/place/controller/PlaceSearchController.java",
    JAVA + "domain/plan/controller/ContextPlanningController.java",
    JAVA + "domain/plan/validator/ContextPlanResultValidator.java",
    JAVA + "domain/plan/repository/ContextPlanRepository.java",
    JAVA + "domain/plan/repository/PlanRepository.java",
    JAVA + "domain/plan/repository/PlanningJobRepository.java",
    JAVA + "ai/llm/base/LlmClient.java",
    JAVA + "ai/llm/derived/OllamaLlmClient.java",
)
SUITES = (
    "com.yollo.TravelMate.SearchEvidencePipelineTest",
    "com.yollo.TravelMate.ContextPlanPipelineTest",
    "com.yollo.TravelMate.PlanContextContractTest",
)


def write_json(path: Path, document: Any) -> None:
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def baseline(path: str) -> str:
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8")


def digests(path: Path) -> dict[str, str]:
    content = path.read_bytes()
    return {"raw_sha256": hashlib.sha256(content).hexdigest(),
            "lf_sha256": hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()}


def segment(source: str, start: str, end: str | None) -> str:
    return source[source.index(start):source.index(end) if end is not None else None]


def main() -> None:
    suites = []
    for name in SUITES:
        path = ROOT / f"Server/TravelMate/build/test-results/test/TEST-{name}.xml"
        suite = ElementTree.parse(path).getroot()
        suites.append({"name": name, **{key: int(suite.attrib[key]) for key in ("tests", "failures", "errors", "skipped")},
                       "test_names": [case.attrib["name"] for case in suite.findall("testcase")],
                       "local_xml_sha256": digests(path)["raw_sha256"]})
    tests = {"suites": suites, **{key: sum(suite[key] for suite in suites) for key in ("tests", "failures", "errors", "skipped")},
             "scope": "Selected offline Java unit tests with mocked JDBC/Kafka result/LLM; no SpringBoot live integration tests.",
             "real_model_calls": 0, "real_search_calls": 0, "production_database_writes": 0}
    assert tests["tests"] == 11 and tests["failures"] == tests["errors"] == tests["skipped"] == 0
    write_json(RUN / "tests.json", tests)
    path = JAVA + "domain/plan/service/ContextPlanningService.java"
    current, original = (ROOT / path).read_text(encoding="utf-8"), baseline(path)
    segments = {
        "direct_draft_save": ("    public PlanningResponse.Draft create(", "    public PlanningResponse.Job job("),
        "existing_request_validation": ("    public static void validateArea(", "    private void runGeneration("),
        "encoding_and_distance": ("    private String encode(", None),
    }
    invariants = {
        "base_commit": BASE,
        "unchanged_files": {path: (ROOT / path).read_text(encoding="utf-8") == baseline(path) for path in UNCHANGED},
        "unchanged_service_segments": {name: segment(current, *bounds) == segment(original, *bounds) for name, bounds in segments.items()},
        "save_call_preserved": "plans.save(userUid, request, normalized, candidates, requestJson)" in current,
        "search_arguments_preserved": "searchService.search(query,null,null,null,10-required.size(),request.context().area())" in "".join(current.split()),
    }
    assert all(invariants["unchanged_files"].values()) and all(invariants["unchanged_service_segments"].values())
    assert invariants["save_call_preserved"] and invariants["search_arguments_preserved"]
    write_json(RUN / "invariants.json", invariants)
    publication = {
        "base_commit": BASE,
        "code": {path: digests(ROOT / path) for path in CODE},
        "docs": {path: digests(ROOT / path) for path in ("docs/architecture/search-evidence-delivery.md", "docs/specifications/contextual-retrieval.md")},
        "files": {path.name: digests(path) for path in sorted(RUN.iterdir()) if path.is_file() and path.name != "publication.json"},
        "hash_basis": "raw_sha256 is local execution bytes; lf_sha256 normalizes CRLF to LF for Git publication.",
    }
    write_json(RUN / "publication.json", publication)
    print(json.dumps({"unit_tests": tests["tests"], "passed": 11, "unchanged_files": len(UNCHANGED), "real_model_calls": 0}))


if __name__ == "__main__":
    main()
