"""Search HTTP evidence is not an agent tool call, generated message, or plan."""
from __future__ import annotations

import hashlib
import json
from typing import Any

from common.dataset.io import canonical_digest
from common.execution.control import AttemptStatus, RunMode
from tracks.search.api_contract import RankingMode, search_body, unsupported_conditions

SEARCH_SOURCE = "spring_search_api"
SEARCH_RECORD_VERSION = "search-api-observation-v2"


def is_search_api_record(record: dict[str, Any]) -> bool:
    return record.get("record_source") == SEARCH_SOURCE


def search_record_error(case: dict[str, Any], record: dict[str, Any]) -> str | None:
    if record.get("schema_version") != SEARCH_RECORD_VERSION:
        return "legacy_search_record_requires_explicit_adaptation"
    try:
        mode = RunMode(record["execution_mode"])
        status = AttemptStatus(record["execution_status"])
        if status == AttemptStatus.STARTED:
            return "unfinished_search_attempt"
        request = record["http_request"]
        receipt = record["attempt_observation"]
        if receipt.get("execution_mode") != mode or receipt.get("dispatched") != record["dispatched"] or receipt.get("attempt_id") != record["request_id"]:
            return "search_attempt_identity_or_mode_mismatch"
        if receipt.get("request") != request or receipt.get("request_sha256") != canonical_digest(request):
            return "search_attempt_request_mismatch"
        if receipt.get("response") != record.get("http_response"):
            return "search_attempt_response_mismatch"
        body = json.loads(request["raw_body"])
        expected = search_body(case, RankingMode(record["ranking_mode"]), record["response_limit"])
        if request["method"] != "POST" or request["route"] != "/api/places/search" or body != expected:
            return "search_request_projection_mismatch"
        if record["requested_conditions"] != case["input"]["conditions"]:
            return "search_original_conditions_mismatch"
        if record["http_request"]["body_sha256"] != hashlib.sha256(request["raw_body"].encode("utf-8")).hexdigest():
            return "search_request_hash_mismatch"
        if record["dispatched"] != (mode == RunMode.LIVE and status != AttemptStatus.NOT_RUN):
            return "search_dispatch_mode_mismatch"
        if status == AttemptStatus.NOT_RUN and (record.get("http_response") is not None or record.get("ranked_place_ids") is not None):
            return "unexecuted_search_cannot_have_results"
        if status == AttemptStatus.COMPLETED:
            response = record["http_response"]
            items = json.loads(response["raw_body"])
            if response["status_code"] != 200 or not isinstance(items, list):
                return "search_response_invalid"
            identifiers = [item["placeId"] for item in items]
            if any(type(identifier) is not int or identifier <= 0 for identifier in identifiers):
                return "search_api_place_ids_invalid"
            if len(identifiers) != len(set(identifiers)) or len(identifiers) > record["response_limit"]:
                return "search_api_rankings_invalid"
            if record["items"] != items or record["ranked_place_ids"] != identifiers:
                return "search_response_provenance_mismatch"
        return None
    except (KeyError, TypeError, ValueError):
        return "search_observation_invalid"


def search_quality_observed(record: dict[str, Any]) -> bool:
    runtime = record.get("runtime_verification") or {}
    return (
        record.get("execution_mode") == RunMode.LIVE
        and record.get("execution_status") == AttemptStatus.COMPLETED
        and record.get("dispatched") is True
        and record.get("condition_coverage") == "complete"
        and record.get("quality_status") != "mock_regression_only"
        and not unsupported_conditions(record.get("requested_conditions") or {})
        and runtime.get("corpus_verified") is True
        and runtime.get("schema_version") == "search-runtime-verification-v2"
        and runtime.get("execution_mode") == RunMode.LIVE
        and runtime.get("configuration_verified") is True
        and runtime.get("search_material_verified") is True
        and isinstance(runtime.get("corpus_sha256"), str)
        and len(runtime["corpus_sha256"]) == 64
        and record.get("observation_coverage", {}).get("search") is True
    )
