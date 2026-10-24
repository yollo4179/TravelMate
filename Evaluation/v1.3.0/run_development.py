"""Capture real Spring search API outputs into the selected evaluation split."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timedelta, timezone
import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum
from typing import Any

import build_dataset
import evaluate_ranking


SERVER_URL = "http://127.0.0.1:8080"
RUNTIME_RESPONSE_SOURCE = "target_system_http_response"


class RankingVersion(Enum):
    V1_SEMANTIC_ONLY = ("v1_semantic_only", "SEMANTIC_ONLY", "api_embedding", "v1.jsonl")
    V2_RERANKED = ("v2_reranked", "RERANKED", "api_reranking", "v2.jsonl")

    @property
    def version_id(self) -> str:
        return self.value[0]

    @property
    def ranking_mode(self) -> str:
        return self.value[1]

    @property
    def output_path(self) -> tuple[str, str]:
        return self.value[2], self.value[3]


def request_json(
    url: str,
    *,
    method: str = "GET",
    body: dict[str, Any] | None = None,
    token: str | None = None,
    timeout: float = 180.0,
) -> tuple[int, str, Any]:
    headers = {"Accept": "application/json"}
    payload = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        payload = json.dumps(body, ensure_ascii=False).encode("utf-8")
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, data=payload, headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            try:
                parsed_body = json.loads(response_body) if response_body else None
            except json.JSONDecodeError:
                parsed_body = response_body
            return response.status, response_body, parsed_body
    except urllib.error.HTTPError as error:
        response_body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned HTTP {error.code}: {response_body[:500]}") from error


def create_temporary_account() -> tuple[str, str, str]:
    suffix = secrets.token_hex(8)
    user_id = f"eval_{suffix}"
    password = secrets.token_urlsafe(24)
    email = f"{user_id}@example.invalid"
    request_json(
        f"{SERVER_URL}/api/users/signup",
        method="POST",
        body={"userId": user_id, "email": email, "password": password, "nickname": user_id},
    )
    _, _, login = request_json(
        f"{SERVER_URL}/api/auth/login",
        method="POST",
        body={"userId": user_id, "password": password},
    )
    token = login.get("accessToken") if isinstance(login, dict) else None
    if not token:
        raise RuntimeError("Temporary evaluation account did not receive an access token")
    return user_id, token, email


def delete_temporary_account(user_id: str, token: str) -> None:
    request_json(f"{SERVER_URL}/api/users/me", method="DELETE", token=token)


def plan_context(case: dict[str, Any]) -> dict[str, Any]:
    area = case["conditions"]["area"]
    center = area["center"]
    now = datetime.now(timezone(timedelta(hours=9))).replace(second=0, microsecond=0)
    end = now + timedelta(hours=1)
    if now.date() != end.date():
        now = now - timedelta(hours=2)
        end = now + timedelta(hours=1)
    coordinate = {"lat": center["latitude"], "lon": center["longitude"]}
    return {
        "area": {
            "type": "CIRCLE",
            "center": coordinate,
            "radiusMeters": area["radius_meters"],
            "regionId": None,
        },
        "origin": {"coordinate": coordinate, "label": "평가용 선택 지점", "source": "SELECTED_POINT"},
        "destination": None,
        "startAt": now.isoformat(),
        "endAt": end.isoformat(),
        "transportMode": "WALK",
        "objective": "DISTANCE",
        "preferences": {"themes": [], "avoid": [], "pace": "NORMAL", "partySize": 1, "budgetKrw": None},
        "categoryRequirements": [],
        "additionalRequest": None,
        "unknownHoursPolicy": "ALLOW_WITH_WARNING",
    }


def unsupported_conditions(case: dict[str, Any], *, radius_supported: bool) -> list[str]:
    conditions = case["conditions"]
    unsupported = [
        field for field in ("exclude_place_ids", "conversation")
        if conditions[field]
    ]
    if conditions["area"] is not None and not radius_supported:
        unsupported.append("area")
    return unsupported


def get_search_result(
    case: dict[str, Any],
    token: str,
    ranking_version: RankingVersion,
    timeout: float,
) -> dict[str, Any]:
    conditions = case["conditions"]
    ranking_parameter = {"rankingMode": ranking_version.ranking_mode}
    if conditions["area"] is not None:
        unsupported = unsupported_conditions(case, radius_supported=True)
        request_body = {"context": plan_context(case), "query": case["query"], "limit": 20}
        method = "POST"
        url = f"{SERVER_URL}/api/v1/places/search?{urllib.parse.urlencode(ranking_parameter)}"
        status, response_body, parsed_response = request_json(
            url,
            method=method,
            body=request_body,
            token=token,
            timeout=timeout,
        )
        applied_conditions = ["area", "query"]
    else:
        unsupported = unsupported_conditions(case, radius_supported=False)
        parameters = {"query": case["query"], "limit": "20", **ranking_parameter}
        for field in ("region", "city", "category"):
            if conditions[field] is not None:
                parameters[field] = conditions[field]
        url = f"{SERVER_URL}/api/places/search?{urllib.parse.urlencode(parameters)}"
        method = "GET"
        status, response_body, parsed_response = request_json(url, token=token, timeout=timeout)
        applied_conditions = ["query", *[field for field in ("region", "city", "category") if conditions[field] is not None]]
    if not isinstance(parsed_response, list):
        raise RuntimeError(f"Search API returned an unexpected payload for {case['case_id']}")
    if any(not isinstance(place, dict) or "description" not in place for place in parsed_response):
        raise RuntimeError(f"Search API returned an invalid place payload for {case['case_id']}")
    return {
        "response": response_body,
        "retrieved_contexts": [place["description"] or "" for place in parsed_response],
        "place_ids": [place["placeId"] for place in parsed_response],
        "execution": {
            "status": "completed",
            "target": "travelmate_spring_search_api",
            "method": method,
            "url": url,
            "http_status": status,
            "request_body": request_body if conditions["area"] is not None else None,
            "requested_conditions": conditions,
            "ranking_version": ranking_version.version_id,
            "ranking_mode": ranking_version.ranking_mode,
            "applied_condition_fields": applied_conditions,
            "unsupported_conditions": unsupported,
            "condition_coverage": "complete" if not unsupported else "partial",
            "response_field_source": RUNTIME_RESPONSE_SOURCE,
            "retrieved_contexts_source": "description_fields_from_target_system_http_response",
            "retrieval_output_eligible": case["answerability"] == "answerable" and not unsupported,
        },
    }


def skipped_result(case: dict[str, Any]) -> dict[str, Any]:
    reason = "현재 Spring 서버에 자연어 대화 응답 API가 없습니다. 검색 API 출력을 답변으로 대체하지 않았습니다."
    return {
        "response": None,
        "retrieved_contexts": [],
        "ranking_comparison": {},
        "execution": {
            "status": "unsupported_target_flow",
            "target": "travelmate_spring_search_api",
            "reason": reason,
            "requested_conditions": case["conditions"],
            "response_field_source": None,
            "ragas_llm_eligible": False,
        },
    }


def update_case_outputs(
    root: build_dataset.Path,
    case_outputs: dict[str, dict[str, Any]],
    run_summary: dict[str, Any],
) -> dict[str, Any]:
    cases = [json.loads(line) for line in (root / "development.jsonl").read_text(encoding="utf-8").splitlines()]
    for case in cases:
        case.setdefault("response", None)
        case.setdefault("retrieved_contexts", [])
        case.setdefault("execution", {"status": "not_run"})
        case.setdefault("ranking_comparison", {})
        output = case_outputs.get(case["case_id"])
        if output is not None:
            case.update(output)
    build_dataset.write_jsonl(root / "development.jsonl", cases)
    build_dataset.write_json(root / "development_run.json", run_summary)
    export_ragas_inputs(root)
    return build_dataset.refresh_runtime_exports(root)


def export_ragas_inputs(root: build_dataset.Path) -> list[dict[str, Any]]:
    cases = [json.loads(line) for line in (root / "development.jsonl").read_text(encoding="utf-8").splitlines()]
    with (root / "review_notes_filled_v1.3.0.csv").open(encoding="utf-8-sig", newline="") as review_file:
        review_rows = list(csv.DictReader(review_file))
    judgments_by_case: dict[str, list[dict[str, Any]]] = {}
    for review_row in review_rows:
        if not review_row["place_id"] or not review_row["relevance"]:
            continue
        judgments_by_case.setdefault(review_row["case_id"], []).append({
            "place_id": int(review_row["place_id"]),
            "place_name": review_row["place_name"],
            "relevance": int(review_row["relevance"]),
            "rationale": review_row["rationale_or_expected_behavior"],
            "evidence": review_row["evidence"],
            "review_status": review_row["review_status"],
            "human_reviewer": review_row["human_reviewer"],
        })
    input_rows_by_version: dict[str, list[dict[str, Any]]] = {
        ranking_version.version_id: [] for ranking_version in RankingVersion
    }
    for case in cases:
        if case["evaluation_track"] == "answer_behavior":
            continue
        for ranking_version in RankingVersion:
            variant = case.get("ranking_comparison", {}).get(ranking_version.version_id, {})
            variant_execution = variant.get("execution", {})
            judgments = judgments_by_case.get(case["case_id"], [])
            judged_place_ids = {judgment["place_id"] for judgment in judgments}
            relevant_place_ids = {
                judgment["place_id"]
                for judgment in judgments
                if judgment["relevance"] >= 2
            }
            retrieved_place_ids = variant.get("place_ids", [])
            judged_retrieved_place_ids = sorted(
                set(retrieved_place_ids) & judged_place_ids
            )
            unjudged_retrieved_place_ids = sorted(
                set(retrieved_place_ids) - judged_place_ids
            )
            input_rows_by_version[ranking_version.version_id].append({
                "case_id": case["case_id"],
                "strategy_version": ranking_version.version_id,
                "user_input": case["query"],
                "response": variant.get("response"),
                "retrieved_contexts": variant.get("retrieved_contexts", []),
                "retrieved_context_ids": variant.get("place_ids", []),
                "reference": case.get("reference"),
                "reference_contexts": [judgment["evidence"] for judgment in judgments if judgment["relevance"] >= 2],
                "judgments": judgments,
                "judgment_source": "review_notes_filled_v1.3.0.csv",
                "judged_retrieved_place_ids": judged_retrieved_place_ids,
                "unjudged_retrieved_place_ids": unjudged_retrieved_place_ids,
                "condition_coverage": variant_execution.get("condition_coverage"),
                "execution_status": variant_execution.get("status", "not_run"),
                "request_duration_seconds": variant_execution.get("duration_seconds"),
                "ranking_eligible": bool(
                    case["answerability"] == "answerable"
                    and variant_execution.get("status") == "completed"
                    and variant_execution.get("condition_coverage") == "complete"
                    and judgments
                ),
                "ragas_id_metrics_eligible": bool(
                    case["answerability"] == "answerable"
                    and variant_execution.get("status") == "completed"
                    and variant_execution.get("condition_coverage") == "complete"
                    and relevant_place_ids
                ),
                "ragas_llm_eligible": bool(
                    case["answerability"] == "answerable"
                    and variant_execution.get("status") == "completed"
                    and variant_execution.get("condition_coverage") == "complete"
                    and case.get("reference")
                ),
            })
    for ranking_version in RankingVersion:
        folder, filename = ranking_version.output_path
        build_dataset.write_jsonl(root / folder / filename, input_rows_by_version[ranking_version.version_id])
    return [row for version_rows in input_rows_by_version.values() for row in version_rows]


def write_ragas_llm_precheck(root: build_dataset.Path) -> dict[str, Any]:
    reranked_rows = [
        json.loads(line)
        for line in (root / "api_reranking" / "v2.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    missing_reference_case_ids = sorted(
        row["case_id"] for row in reranked_rows if not row.get("reference")
    )
    faithfulness_input_rows = [
        row
        for row in reranked_rows
        if row.get("execution_status") == "completed"
        and row.get("condition_coverage") == "complete"
        and row.get("response")
        and row.get("retrieved_contexts")
    ]
    reference_blocked_status = (
        "not_run_missing_reference"
        if missing_reference_case_ids
        else "not_run_batch_deferred"
    )
    precheck = {
        "status": "not_run_batch_prerequisites_incomplete",
        "execution_policy": {
            "mode": "all_or_none",
            "reason": "The three selected LLM metrics are evaluated as one batch; execution is deferred until required references and an LLM evaluator are configured.",
        },
        "metrics": {
            "answer_correctness": {
                "status": reference_blocked_status,
                "reference_required": True,
                "missing_reference_case_ids": missing_reference_case_ids,
                "llm_evaluator_configured": False,
            },
            "context_recall": {
                "status": reference_blocked_status,
                "reference_required": True,
                "missing_reference_case_ids": missing_reference_case_ids,
                "llm_evaluator_configured": False,
            },
            "faithfulness": {
                "status": "not_run_llm_evaluator_not_configured",
                "reference_required": False,
                "input_ready_case_ids": sorted(row["case_id"] for row in faithfulness_input_rows),
                "llm_evaluator_configured": False,
                "deferred_by_batch_policy": True,
            },
        },
        "score_count": 0,
        "requested_metrics": ["answer_correctness", "faithfulness", "context_recall"],
        "note": "Faithfulness does not require a reference, but it still requires an LLM evaluator. ID-based RAGAS scores are recorded separately in ragas_summary.json.",
    }
    build_dataset.write_json(root / "ragas_llm_precheck.json", precheck)
    return precheck


def run_split(
    root: build_dataset.Path,
    split: str,
    *,
    case_ids: set[str] | None = None,
    timeout: float = 600.0,
    max_workers: int = 1,
) -> dict[str, Any]:
    all_cases = [json.loads(line) for line in (root / f"{split}.jsonl").read_text(encoding="utf-8").splitlines()]
    cases = [case for case in all_cases if case_ids is None or case["case_id"] in case_ids]
    if case_ids is not None and {case["case_id"] for case in cases} != case_ids:
        missing_case_ids = sorted(case_ids - {case["case_id"] for case in cases})
        raise ValueError(f"Unknown case IDs for {split}: {', '.join(missing_case_ids)}")
    user_id, token, _ = create_temporary_account()
    case_outputs: dict[str, dict[str, Any]] = {}
    statuses: Counter[str] = Counter()
    ragas_llm_eligible: list[str] = []
    missing_reference: list[str] = []
    started_at = datetime.now(timezone.utc).isoformat()
    case_by_id = {case["case_id"]: case for case in cases}

    def execute_case(case: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        started = time.monotonic()
        if case["evaluation_track"] == "answer_behavior":
            output = skipped_result(case)
        else:
            versions: dict[str, dict[str, Any]] = {}
            for ranking_version in RankingVersion:
                version_started = time.monotonic()
                try:
                    versions[ranking_version.version_id] = get_search_result(
                        case,
                        token,
                        ranking_version,
                        timeout,
                    )
                except (OSError, RuntimeError, TimeoutError) as error:
                    versions[ranking_version.version_id] = {
                        "response": None,
                        "retrieved_contexts": [],
                        "place_ids": [],
                        "execution": {
                            "status": "request_failed",
                            "ranking_version": ranking_version.version_id,
                            "error_type": type(error).__name__,
                            "error": str(error),
                            "retrieval_output_eligible": False,
                        },
                    }
                versions[ranking_version.version_id]["execution"]["duration_seconds"] = round(
                    time.monotonic() - version_started,
                    3,
                )
            reranked = versions[RankingVersion.V2_RERANKED.version_id]
            completed_versions = [
                result for result in versions.values()
                if result["execution"]["status"] == "completed"
            ]
            output = {
                "response": reranked["response"],
                "retrieved_contexts": reranked["retrieved_contexts"],
                "ranking_comparison": {
                    version: {
                        key: value for key, value in result.items() if key != "execution"
                    } | {"execution": result["execution"]}
                    for version, result in versions.items()
                },
                "execution": {
                    "status": "completed" if len(completed_versions) == len(RankingVersion) else "request_failed",
                    "target": "travelmate_spring_search_api",
                    "ranking_versions": {version: result["execution"] for version, result in versions.items()},
                    "condition_coverage": "complete" if all(
                        result["execution"].get("condition_coverage") == "complete"
                        for result in completed_versions
                    ) else "partial",
                    "response_field_source": RUNTIME_RESPONSE_SOURCE if reranked["response"] is not None else None,
                    "ragas_llm_eligible": bool(reranked["execution"].get("ragas_llm_eligible")) and bool(case["reference"]),
                },
            }
        output["execution"]["duration_seconds"] = round(time.monotonic() - started, 3)
        output["execution"]["case_id"] = case["case_id"]
        return case["case_id"], output

    def save_progress(*, complete: bool, account_deleted: bool) -> dict[str, Any]:
        summary = {
            "status": ("completed" if statuses["request_failed"] == 0 else "completed_with_errors") if complete else "in_progress",
            "split": split,
            "dataset_version": "1.3.0",
            "started_at": started_at,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "case_count": len(cases),
            "split_case_count": len(all_cases),
            "selection_scope": "all_cases" if case_ids is None else "selected_cases",
            "selected_case_ids": sorted(case_ids) if case_ids is not None else None,
            "completed_case_count": len(case_outputs),
            "execution_counts": dict(statuses),
            "ragas_llm_eligible_case_ids": sorted(ragas_llm_eligible),
            "ragas_llm_skipped_missing_reference_case_ids": sorted(missing_reference),
            "temporary_account": {"created": True, "deleted": account_deleted, "email_domain": "example.invalid"},
            "endpoint_capabilities": {
                "GET /api/places/search": ["query", "region", "city", "category"],
                "POST /api/v1/places/search": ["query", "circular_area"],
                "unsupported": ["place_exclusion", "conversation_history", "answer_behavior_generation"],
            },
            "ragas_llm_metrics_requested": ["answer_correctness", "faithfulness", "context_recall"],
            "ranking_versions": {
                version.version_id: {"ranking_mode": version.ranking_mode}
                for version in RankingVersion
            },
            "notes": [
                "response contains the raw target API response body, not a synthesized answer.",
                "retrieved_contexts comes only from description fields in that response.",
                "Cases with unsupported conditions are recorded but excluded from RAGAS scores.",
                "Answer-behavior cases remain unexecuted because the target server exposes no conversation answer endpoint.",
                "Reference-based RAGAS metrics are skipped when no authored reference exists.",
            ],
        }
        update_case_outputs(root, case_outputs, summary)
        return summary

    try:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(execute_case, case) for case in cases]
            for future in as_completed(futures):
                case_id, output = future.result()
                case_outputs[case_id] = output
                statuses[output["execution"]["status"]] += 1
                if output["execution"].get("ragas_llm_eligible"):
                    ragas_llm_eligible.append(case_id)
                elif output["execution"].get("ranking_versions") and not case_by_id[case_id]["reference"]:
                    missing_reference.append(case_id)
                save_progress(complete=False, account_deleted=False)
                print(f"{split}: {case_id} {output['execution']['status']} ({len(case_outputs)}/{len(cases)})", flush=True)
    finally:
        delete_temporary_account(user_id, token)
    run_summary = save_progress(complete=True, account_deleted=True)
    run_summary["finished_at"] = datetime.now(timezone.utc).isoformat()
    build_dataset.write_json(root / "development_run.json", run_summary)
    build_dataset.refresh_runtime_exports(root)
    ranking_summary = evaluate_ranking.evaluate(root)
    run_summary["ranking_evaluation"] = {
        "status": ranking_summary["status"],
        "case_count": ranking_summary["case_count"],
        "ranking_versions": ranking_summary["ranking_versions"],
        "delta_v2_minus_v1": ranking_summary["delta_v2_minus_v1"],
    }
    build_dataset.write_json(root / "development_run.json", run_summary)
    write_ragas_llm_precheck(root)
    build_dataset.refresh_runtime_exports(root)
    return run_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(build_dataset.ROOT))
    parser.add_argument("--split", choices=("development",), default="development")
    parser.add_argument("--case-id", action="append", dest="case_ids")
    parser.add_argument("--timeout-seconds", type=float, default=600.0)
    parser.add_argument("--max-workers", type=int, default=1)
    arguments = parser.parse_args()
    summary = run_split(
        build_dataset.Path(arguments.root),
        arguments.split,
        case_ids=set(arguments.case_ids) if arguments.case_ids else None,
        timeout=arguments.timeout_seconds,
        max_workers=arguments.max_workers,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
