"""관찰 경계·이동 관계의 선택 계약을 고정 사례에서 검수한다. 검색·DB 적용은 하지 않는다."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from decimal import Decimal
import json
from pathlib import Path
import sys
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "embedding-server"))
from app.contextual.agent import request_payload
from app.contextual.artifacts import load_record
from app.contextual.contracts import SplitterVersion
from app.contextual.input_format import InputVersion
from app.contextual.prompts import PromptVersion
from app.contextual.replay import GenerationBaseline
from app.enrichment.artifacts import write_json
from Evaluation.tracks.contextual.span_generation import execute_verified_plan, read_json, raw_chunks, sha256
from Evaluation.tracks.contextual.prompt_comparison import request_digest


COMPARISON_KIND = "observation-splitting-and-relations-v6"


def candidate_request(baseline: GenerationBaseline) -> dict[str, Any]:
    if baseline.record["prompt_version"] != PromptVersion.V5 or baseline.record["input_version"] != InputVersion.EXPLICIT:
        raise ValueError("보존된 v5 명시적 입력 응답을 대조군으로 사용합니다")
    candidate = request_payload(baseline.bundle.places, baseline.bundle.sources, baseline.settings("", 180),
        prompt_version=PromptVersion.V6, input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
    changed = {key for key in set(candidate) | set(baseline.request) if candidate.get(key) != baseline.request.get(key)}
    if changed != {"input", "instructions", "response_format"}:
        raise ValueError("원문 분할·지시문·출력 계약 외 요청 설정이 다릅니다")
    return candidate


def prepare(summary_path: Path, regression_path: Path, output: Path, selected: list[str]) -> Path:
    if output.exists() or output.resolve().is_relative_to((REPOSITORY / "Evaluation/datasets").resolve()):
        raise ValueError("기존 실행 또는 동결 데이터에 쓸 수 없습니다")
    source = read_json(summary_path)
    if not source["comparison_complete"] or len(set(selected)) != len(selected):
        raise ValueError("완료된 대조군과 중복 없는 묶음 ID가 필요합니다")
    mapping = {row["id"]: row for row in source["results"]}
    if not selected or len(selected) > 9 or not set(selected).issubset(mapping):
        raise ValueError("존재하는 1~9개 묶음을 명시해야 합니다")
    pairs = []
    originals = {}
    for identifier in selected:
        path = Path(mapping[identifier]["candidate_record"])
        baseline = GenerationBaseline.load(path)
        payload = candidate_request(baseline)
        pairs.append({"id": identifier, "baseline_record": str(path), "request": payload,
                      "request_sha256": request_digest(payload)})
        for name in ("record.json", "request.json", "sources.json", "raw_response.json"):
            originals[str(path.with_name(name))] = sha256(path.with_name(name))
    plan = {"comparison_kind": COMPARISON_KIND, "maximum_new_calls": len(pairs), "pairs": pairs,
        "summary_path": str(summary_path.resolve()), "summary_sha256": sha256(summary_path),
        "regression_path": str(regression_path.resolve()), "regression_sha256": sha256(regression_path),
        "original_file_sha256": originals, "search_executions": 0, "database_writes": 0}
    output.mkdir(parents=True)
    path = output / "plan.json"
    write_json(path, plan)
    verified_plan(path)
    return path


def verified_plan(path: Path) -> dict[str, Any]:
    plan = read_json(path)
    if (plan["comparison_kind"] != COMPARISON_KIND or not 1 <= len(plan["pairs"]) <= 9
            or plan["maximum_new_calls"] != len(plan["pairs"])
            or len({row["id"] for row in plan["pairs"]}) != len(plan["pairs"])):
        raise ValueError("관찰 계약 검수의 호출 상한·대상이 다릅니다")
    for prefix in ("summary", "regression"):
        if sha256(Path(plan[prefix + "_path"])) != plan[prefix + "_sha256"]:
            raise ValueError("고정 회귀 사례 또는 대조군 목록이 바뀌었습니다")
    for filename, digest in plan["original_file_sha256"].items():
        if sha256(Path(filename)) != digest:
            raise ValueError("보존 대조군이 바뀌었습니다")
    for pair in plan["pairs"]:
        baseline = GenerationBaseline.load(Path(pair["baseline_record"]))
        if candidate_request(baseline) != pair["request"] or request_digest(pair["request"]) != pair["request_sha256"]:
            raise ValueError("검토한 관찰 계약 요청이 다릅니다")
    return plan


def audit(plan_path: Path) -> dict[str, Any]:
    plan = verified_plan(plan_path)
    summary = read_json(plan_path.with_name("generation-summary.json"))
    if not summary["comparison_complete"] or summary["plan_sha256"] != sha256(plan_path):
        raise ValueError("계획과 일치하는 생성 완료 기록이 필요합니다")
    if [row["id"] for row in summary["results"]] != [row["id"] for row in plan["pairs"]]:
        raise ValueError("생성 묶음이 누락·중복됐습니다")
    if (len(list(plan_path.with_name("http-attempts").glob("*.json"))) != summary["api_calls"]
            or sum(row["api_calls"] for row in summary["results"]) != summary["api_calls"]):
        raise ValueError("전송 시도와 실제 호출 집계가 다릅니다")
    cost = Decimal("0")
    response_ids = set()
    results = []
    for actual, planned in zip(summary["results"], plan["pairs"]):
        path = Path(actual["candidate_record"])
        _, chunks, record = load_record(path)
        baseline = GenerationBaseline.load(Path(planned["baseline_record"]))
        if (read_json(path.with_name("request.json")) != planned["request"]
                or record["splitter_version"] != SplitterVersion.SENTENCE
                or record["prompt_version"] != PromptVersion.V6 or record["actual_model"] != baseline.actual_model):
            raise ValueError("실제 요청·분할·응답 모델이 다릅니다")
        raw = read_json(path.with_name("raw_response.json"))
        if raw["usage"]["cost"]["currency"] != "USD":
            raise ValueError("비용 통화가 다릅니다")
        cost += Decimal(str(raw["usage"]["cost"]["total_cost"]))
        response_ids.add(raw["id"])
        results.append({"id": actual["id"], "generated_spans": len(raw_chunks(path)),
            "indexable": len(chunks), "excluded": len(record["excluded_chunks"]),
            "kinds": dict(Counter(item["content_kind"] for item in raw_chunks(path))),
            "actual_model": record["actual_model"], "request_sha256": sha256(path.with_name("request.json")),
            "response_sha256": sha256(path.with_name("raw_response.json"))})
    if len(response_ids) != len(results):
        raise ValueError("서로 다른 입력의 응답 ID가 중복됐습니다")
    return {"comparison_kind": COMPARISON_KIND, "api_calls": summary["api_calls"],
        "provider_reported_cost_usd": str(cost), "results": results,
        "baseline_generation_calls": 0, "search_executions": 0, "database_writes": 0}


def export(plan_path: Path) -> Path:
    audit(plan_path)
    plan = verified_plan(plan_path)
    results = read_json(plan_path.with_name("generation-summary.json"))["results"]
    document = review_records(results, read_json(Path(plan["regression_path"])))
    path = plan_path.with_name("review-inputs.json")
    write_json(path, document)
    return path


def review_records(results: list[dict[str, Any]], regressions_document: dict[str, Any]) -> dict[str, Any]:
    rows = []
    regressions = []
    for result in results:
        path = Path(result["candidate_record"])
        bundle, chunks, _ = load_record(path)
        known = {(chunk.source.source_id, chunk.start, chunk.end): chunk for chunk in chunks}
        sources = {source.source_id: source for source in bundle.sources}
        raw = {(row["source_id"], row["start"], row["end"]): row for row in raw_chunks(path)}
        request = read_json(path.with_name("request.json"))
        for number, span in enumerate(json.loads(request["input"])["spans"], 1):
            key = (span["source_id"], span["start"], span["end"])
            chunk = known.get(key)
            rows.append({"id": f'{result["id"]}-N{number:03d}', "pair_id": result["id"],
                "chunk_id": chunk.chunk_id if chunk else None, "chunk_text": span["chunk_text"],
                **raw[key]})
        for case in regressions_document["cases"]:
            if case["pair_id"] != result["id"]:
                continue
            source = sources[case["source_id"]]
            if source.source_version != case["source_version"] or source.text[case["start"]:case["end"]] != case["anchor"]:
                raise ValueError("고정 회귀 사례의 원문·위치가 다릅니다")
            matches = [row for row in rows if row["pair_id"] == result["id"] and row["source_id"] == source.source_id
                       and row["start"] < case["end"] and case["start"] < row["end"]]
            subjects = {ref["place_id"] for row in matches if row["chunk_id"] is not None
                        for ref in row["place_refs"] if ref["role"] == "subject"}
            passed = bool(matches) and (not subjects.intersection(case.get("forbidden_subject_ids", [])))
            if case.get("required_subject_id") is not None:
                passed = passed and case["required_subject_id"] in subjects
            if case.get("required_kind"):
                passed = passed and all(row["content_kind"] == case["required_kind"] for row in matches)
            if case.get("required_kind") == "movement" and case.get("required_subject_id") is not None:
                passed = passed and any(relation["destination"]["place_id"] == case["required_subject_id"]
                    for row in matches for relation in row["relations"])
            regressions.append({"id": case["id"], "passed": passed, "matched_rows": [row["id"] for row in matches],
                                "indexable_subject_ids": sorted(subjects),
                                "model_subject_ids": sorted({ref["place_id"] for row in matches
                                    for ref in row["place_refs"] if ref["role"] == "subject"})})
    return {"rows": rows, "fixed_regressions": regressions,
            "note": "회귀 검사는 고정 위치의 역할·내용 종류 검사다. 문맥 의미의 전수 검수는 별도다."}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--summary", type=Path, required=True)
    preparation.add_argument("--regressions", type=Path, required=True)
    preparation.add_argument("--pairs", nargs="+", required=True)
    preparation.add_argument("--output", type=Path, required=True)
    generation = commands.add_parser("generate")
    generation.add_argument("--plan", type=Path, required=True)
    generation.add_argument("--key-file", type=Path, required=True)
    generation.add_argument("--execute", action="store_true", required=True)
    for name in ("audit", "export"):
        commands.add_parser(name).add_argument("--plan", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.summary, args.regressions, args.output, args.pairs))
    elif args.command == "generate":
        path = asyncio.run(execute_verified_plan(args.plan, args.key_file, verified_plan(args.plan),
            prompt_version=PromptVersion.V6, splitter_version=SplitterVersion.SENTENCE, preserve_profile=False))
        print(path)
        raise SystemExit(0 if read_json(path)["comparison_complete"] else 1)
    elif args.command == "audit":
        print(json.dumps(audit(args.plan), ensure_ascii=False))
    else:
        print(export(args.plan))


if __name__ == "__main__":
    main()
