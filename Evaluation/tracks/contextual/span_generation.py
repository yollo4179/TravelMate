"""보존 원문에 명시적 청크 입력과 v5를 함께 적용하고 생성 응답만 검수한다."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any
import uuid

import httpx

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "embedding-server"))
from app.contextual.artifacts import collect_bundle, load_record
from app.contextual.input_format import InputVersion
from app.contextual.input_replay import InputFormatComparison
from app.contextual.prompts import PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline
from app.contextual.contracts import SplitterVersion
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import CollectionStatus
from Evaluation.tracks.contextual.prompt_comparison import read_api_key, request_digest
from Evaluation.tracks.contextual.span_inputs import audit_batch


class ComparisonKind(StrEnum):
    INPUT_AND_INSTRUCTIONS = "explicit-input-and-instructions"


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def candidate_request(baseline: GenerationBaseline) -> dict[str, Any]:
    if baseline.record["prompt_version"] != PromptVersion.V4:
        raise ValueError("이번 검수의 대조군은 보존된 v4 응답입니다")
    request = InputFormatComparison(baseline).candidate_request(PromptVersion.V4)
    request["instructions"] = resolve_prompt(PromptVersion.V5).instructions
    if {key for key in request if request[key] != baseline.request[key]} != {"input", "instructions"}:
        raise ValueError("입력과 지시문 외 변경이 있거나 변경 대상이 누락됐습니다")
    return request


def prepare(batch_path: Path, prepared_path: Path, output: Path) -> Path:
    if output.resolve().is_relative_to((REPOSITORY / "Evaluation/datasets").resolve()) or output.exists():
        raise ValueError("동결 데이터 또는 기존 실행 폴더에 쓸 수 없습니다")
    audit_batch(batch_path)
    batch = read_json(batch_path)
    labels = read_json(prepared_path)["rows"]
    pairs = []
    for item in batch["pairs"]:
        source = read_json(Path(item["plan"]))
        baseline = GenerationBaseline.load(Path(source["baseline_record"]))
        request = candidate_request(baseline)
        spans = json.loads(request["input"])["spans"]
        expected = {(row["source_id"], row["start"], row["end"]) for row in labels if row["pair_id"] == item["id"]}
        if expected != {(span["source_id"], span["start"], span["end"]) for span in spans}:
            raise ValueError("검수 ID와 실제 입력 구간이 다릅니다")
        pairs.append({"id": item["id"], "baseline_record": source["baseline_record"],
                      "request": request, "request_sha256": request_digest(request)})
    if not 1 <= len(pairs) <= 9:
        raise ValueError("이번 실행은 최대 9개 보존 입력으로 제한합니다")
    output.mkdir(parents=True)
    path = output / "plan.json"
    write_json(path, {"created_at": datetime.now(UTC).isoformat(),
        "comparison_kind": ComparisonKind.INPUT_AND_INSTRUCTIONS.value,
        "batch_plan": str(batch_path.resolve()), "batch_sha256": sha256(batch_path),
        "prepared_path": str(prepared_path.resolve()), "prepared_sha256": sha256(prepared_path),
        "prompt_version": PromptVersion.V5.value, "input_version": InputVersion.EXPLICIT.value,
        "maximum_new_calls": len(pairs), "pairs": pairs, "search_executions": 0,
        "split_candidates_applied": False})
    return path


def verified_plan(path: Path) -> dict[str, Any]:
    plan = read_json(path)
    if (plan["comparison_kind"] != ComparisonKind.INPUT_AND_INSTRUCTIONS
            or plan["prompt_version"] != PromptVersion.V5 or plan["input_version"] != InputVersion.EXPLICIT
            or not 1 <= len(plan["pairs"]) <= 9 or plan["maximum_new_calls"] != len(plan["pairs"])):
        raise ValueError("이번 생성 검수의 실행 조건이 다릅니다")
    batch_path = Path(plan["batch_plan"])
    if sha256(batch_path) != plan["batch_sha256"] or sha256(Path(plan["prepared_path"])) != plan["prepared_sha256"]:
        raise ValueError("실행 준비 자료의 해시가 바뀌었습니다")
    audit_batch(batch_path)
    originals = read_json(batch_path)["pairs"]
    if [row["id"] for row in originals] != [row["id"] for row in plan["pairs"]]:
        raise ValueError("생성 대상이 추가·중복·누락됐습니다")
    for pair, original in zip(plan["pairs"], originals):
        source = read_json(Path(original["plan"]))
        if pair["baseline_record"] != source["baseline_record"]:
            raise ValueError("비교 원본이 바뀌었습니다")
        baseline = GenerationBaseline.load(Path(pair["baseline_record"]))
        if pair["request"] != candidate_request(baseline) or request_digest(pair["request"]) != pair["request_sha256"]:
            raise ValueError("실행 요청이 검토한 입력·지시문과 다릅니다")
    return plan


async def generate(
    plan_path: Path,
    key_path: Path,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Path:
    plan = verified_plan(plan_path)
    return await execute_verified_plan(plan_path, key_path, plan, transport=transport)


async def execute_verified_plan(
    plan_path: Path,
    key_path: Path,
    plan: dict[str, Any],
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    prompt_version: str = PromptVersion.V5,
    splitter_version: str = SplitterVersion.LEGACY,
    preserve_profile: bool = True,
) -> Path:
    output = plan_path.parent
    summary_path = output / "generation-summary.json"
    if summary_path.exists() or (output / "http-attempts").exists():
        raise ValueError("기존 호출 기록이 있어 자동 재시도하지 않습니다")
    api_key = read_api_key(key_path)
    calls = 0
    results = []
    error_type = None

    async def count_request(request: httpx.Request) -> None:
        nonlocal calls
        if calls >= plan["maximum_new_calls"]:
            raise ValueError("유료 요청 상한을 초과했습니다")
        calls += 1
        write_json(output / "http-attempts" / f"{uuid.uuid4()}.json", {
            "created_at": datetime.now(UTC).isoformat(),
            "request_sha256": request_digest(json.loads(request.content)), "status": "attempted"})

    async def record_error_response(response: httpx.Response) -> None:
        if not response.is_error:
            return
        body = (await response.aread()).decode("utf-8", errors="replace")
        body = re.sub(r"pplx-[A-Za-z0-9_-]+", "[REDACTED]", body.replace(api_key, "[REDACTED]"))
        write_json(output / "http-errors" / f"{uuid.uuid4()}.json", {
            "status_code": response.status_code,
            "content_type": response.headers.get("content-type"),
            "request_id": response.headers.get("x-request-id") or response.headers.get("request-id"),
            "body_preview": body[:4096],
        })

    try:
        async with httpx.AsyncClient(transport=transport, event_hooks={
            "request": [count_request], "response": [record_error_response]}) as client:
            for pair in plan["pairs"]:
                baseline = GenerationBaseline.load(Path(pair["baseline_record"]))
                before = calls
                path = await collect_bundle(
                    baseline.bundle,
                    baseline.settings(api_key, 180),
                    output / "g",
                    client,
                    prompt_version=prompt_version,
                    prepared_request=pair["request"],
                    request_profile_id=baseline.request_profile_id if preserve_profile else None,
                    input_version=InputVersion.EXPLICIT,
                    splitter_version=splitter_version,
                )
                record = read_json(path)
                model_match = record.get("actual_model") == baseline.actual_model
                result = {"id": pair["id"], "candidate_record": str(path.resolve()),
                    "baseline_record": pair["baseline_record"], "status": record["status"],
                    "actual_model_match": model_match, "api_calls": calls - before,
                    "usage": record.get("usage"), "error_type": record.get("error_type"),
                    "http_status": record.get("http_status")}
                results.append(result)
                print(json.dumps({key: result[key] for key in ("id", "status", "actual_model_match", "api_calls")}), flush=True)
                if record["status"] != CollectionStatus.COLLECTED or not model_match:
                    break
                load_record(path)
    except Exception as exception:
        error_type = type(exception).__name__
    complete = (error_type is None and len(results) == len(plan["pairs"])
                and all(row["status"] == CollectionStatus.COLLECTED and row["actual_model_match"] for row in results))
    write_json(summary_path, {"created_at": datetime.now(UTC).isoformat(), "plan_sha256": sha256(plan_path),
        "comparison_complete": complete, "comparison_kind": plan["comparison_kind"],
        "api_calls": calls, "baseline_generation_calls": 0,
        "key_source": "explicit_key_file", "search_executions": 0, "error_type": error_type,
        "results": results})
    return summary_path


def raw_chunks(path: Path) -> list[dict[str, Any]]:
    raw = read_json(path.with_name("raw_response.json"))
    text = "".join(part["text"] for item in raw["output"] if item.get("type") == "message"
                   for part in item.get("content", []) if part.get("type") == "output_text")
    return json.loads(text)["chunks"]


def audit(plan_path: Path) -> dict[str, Any]:
    plan = verified_plan(plan_path)
    summary = read_json(plan_path.with_name("generation-summary.json"))
    if summary["plan_sha256"] != sha256(plan_path) or not summary["comparison_complete"]:
        raise ValueError("계획과 일치하는 생성 완료 기록이 필요합니다")
    if [row["id"] for row in summary["results"]] != [row["id"] for row in plan["pairs"]]:
        raise ValueError("생성 완료 기록의 묶음이 다릅니다")
    attempts = list(plan_path.with_name("http-attempts").glob("*.json"))
    if (len(attempts) != summary["api_calls"]
            or sum(row["api_calls"] for row in summary["results"]) != summary["api_calls"]
            or summary["api_calls"] > plan["maximum_new_calls"]):
        raise ValueError("실제 전송 시도·묶음 집계·호출 상한이 다릅니다")
    total_cost = Decimal("0")
    response_ids = set()
    results = []
    for result, planned in zip(summary["results"], plan["pairs"]):
        path = Path(result["candidate_record"])
        baseline = GenerationBaseline.load(Path(planned["baseline_record"]))
        _, chunks, record = load_record(path)
        if (read_json(path.with_name("request.json")) != planned["request"]
                or record["input_version"] != InputVersion.EXPLICIT
                or record["prompt_version"] != PromptVersion.V5
                or record["validation_version"] != baseline.record["validation_version"]
                or record["actual_model"] != baseline.actual_model):
            raise ValueError("실제 요청·입력·검증 규칙·응답 모델이 다릅니다")
        raw = read_json(path.with_name("raw_response.json"))
        response_ids.add(raw["id"])
        cost = raw["usage"]["cost"]
        if cost["currency"] != "USD":
            raise ValueError("공급자 사용량 통화가 다릅니다")
        total_cost += Decimal(str(cost["total_cost"]))
        results.append({"id": result["id"], "actual_model": raw["model"], "indexable": len(chunks),
            "excluded": len(record["excluded_chunks"]), "reported_cost_usd": cost["total_cost"],
            "request_sha256": sha256(path.with_name("request.json")),
            "response_sha256": sha256(path.with_name("raw_response.json"))})
    if len(response_ids) != len(results):
        raise ValueError("서로 다른 입력의 응답 ID가 중복됐습니다")
    return {"generation_pairs_verified": len(results), "unique_provider_responses": len(response_ids),
        "comparison_kind": ComparisonKind.INPUT_AND_INSTRUCTIONS.value,
        "provider_reported_cost_usd": str(total_cost), "api_calls": summary["api_calls"],
        "baseline_generation_calls": 0, "search_executions": 0, "results": results}


def review_document(plan_path: Path) -> dict[str, Any]:
    audit(plan_path)
    plan = verified_plan(plan_path)
    summary = read_json(plan_path.with_name("generation-summary.json"))
    labels = read_json(Path(plan["prepared_path"]))["rows"]
    rows = []
    for pair in summary["results"]:
        before = Path(pair["baseline_record"])
        after = Path(pair["candidate_record"])
        baseline = GenerationBaseline.load(before)
        sources = {source.source_id: source for source in baseline.bundle.sources}
        mapped = {name: {(item["source_id"], item["start"], item["end"]): item for item in raw_chunks(path)}
                  for name, path in (("v4", before), ("v5", after))}
        for label in (row for row in labels if row["pair_id"] == pair["id"]):
            key = (label["source_id"], label["start"], label["end"])
            source = sources[label["source_id"]]
            rows.append({"id": label["id"], "source_id": source.source_id, "source_version": source.source_version,
                "start": label["start"], "end": label["end"], "chunk_text": source.text[label["start"]:label["end"]],
                "v4": deepcopy(mapped["v4"][key]), "v5": deepcopy(mapped["v5"][key])})
    return {"comparison_kind": plan["comparison_kind"], "rows": rows}


def export_review(plan_path: Path) -> Path:
    path = plan_path.with_name("review-inputs.json")
    write_json(path, review_document(plan_path))
    return path


def summarize_review(plan_path: Path, review_path: Path) -> dict[str, Any]:
    inputs = read_json(plan_path.with_name("review-inputs.json"))
    if inputs != review_document(plan_path):
        raise ValueError("검수 입력이 보존된 실제 응답·원문과 다릅니다")
    review = read_json(review_path)
    if review["comparison_kind"] != inputs["comparison_kind"]:
        raise ValueError("검수의 비교 조건이 실제 생성 조건과 다릅니다")
    prior = read_json(REPOSITORY / "Evaluation/tracks/contextual/prompt_v4_review.json")
    by_id = {row["id"]: row for row in review["rows"]}
    old_by_id = {row["id"]: row for row in prior["rows"]}
    if (len(by_id) != len(review["rows"]) or set(by_id) != {row["id"] for row in inputs["rows"]}
            or set(by_id) != set(old_by_id)):
        raise ValueError("검수 항목이 중복·누락되거나 기준군과 다릅니다")
    counts = {"v4": Counter(), "v5": Counter()}
    indexable = {"v4": 0, "v5": 0}
    role_changes = []
    for row in inputs["rows"]:
        before = old_by_id[row["id"]]["v4"]
        after = by_id[row["id"]]["v5"]
        if len(set(after)) != len(after) or not set(after).issubset(review["rubric"]):
            raise ValueError("검수 유형이 중복됐거나 검수 기준에 없는 유형입니다")
        counts["v4"].update(before)
        counts["v5"].update(after)
        for version in ("v4", "v5"):
            indexable[version] += int(any(ref["role"] == "subject" for ref in row[version]["place_refs"]))
        if row["v4"]["place_refs"] != row["v5"]["place_refs"]:
            role_changes.append({"id": row["id"], "v4": row["v4"]["place_refs"], "v5": row["v5"]["place_refs"]})
    return {"reviewed_spans": len(by_id), "comparison_kind": inputs["comparison_kind"],
        "reviewer": review["reviewer"], "independent_blind_review": False,
        "review_sha256": sha256(review_path), "review_inputs_sha256": sha256(plan_path.with_name("review-inputs.json")),
        "prior_review_sha256": sha256(REPOSITORY / "Evaluation/tracks/contextual/prompt_v4_review.json"),
        "flag_counts": {version: dict(counts[version]) for version in counts},
        "span_topic_replaced": {version: counts[version]["span_topic_replaced"] for version in counts},
        "wrong_place_attribution": {version: counts[version]["wrong_place_attribution"] for version in counts},
        "indexable_chunks": indexable, "excluded_chunks": {version: len(by_id) - count for version, count in indexable.items()},
        "role_changes": role_changes, "search_performance_evaluated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    preparation = commands.add_parser("prepare")
    preparation.add_argument("--batch", type=Path, required=True)
    preparation.add_argument("--prepared", type=Path, required=True)
    preparation.add_argument("--output", type=Path, required=True)
    generation = commands.add_parser("generate")
    generation.add_argument("--plan", type=Path, required=True)
    generation.add_argument("--key-file", type=Path, required=True)
    generation.add_argument("--execute", action="store_true", required=True)
    for command in ("audit", "export-review"):
        commands.add_parser(command).add_argument("--plan", type=Path, required=True)
    review = commands.add_parser("summarize-review")
    review.add_argument("--plan", type=Path, required=True)
    review.add_argument("--review", type=Path, required=True)
    review.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.batch, args.prepared, args.output))
    elif args.command == "generate":
        path = asyncio.run(generate(args.plan, args.key_file))
        print(path)
        raise SystemExit(0 if read_json(path)["comparison_complete"] else 1)
    elif args.command == "audit":
        print(json.dumps(audit(args.plan), ensure_ascii=False))
    elif args.command == "summarize-review":
        write_json(args.output, summarize_review(args.plan, args.review))
        print(args.output)
    else:
        print(export_review(args.plan))


if __name__ == "__main__":
    main()
