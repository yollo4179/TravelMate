"""Build traceable search judgments from a frozen, read-only database export."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
import re
from collections import Counter
from enum import Enum, IntEnum
from pathlib import Path
from typing import Any


class CaseType(str, Enum):
    EXACT_NAME = "exact_name"
    SEMANTIC = "semantic"
    MULTIPLE_RELEVANT = "multiple_relevant"
    CONTEXT_CONSTRAINTS = "context_constraints"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CLARIFICATION_REQUIRED = "clarification_required"


class Answerability(str, Enum):
    ANSWERABLE = "answerable"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    CLARIFICATION_REQUIRED = "clarification_required"


class Relevance(IntEnum):
    IRRELEVANT = 0
    MARGINAL = 1
    RELATED = 2
    DIRECT = 3


class Split(str, Enum):
    DEVELOPMENT = "development"
    TEST = "test"


class ReviewStatus(str, Enum):
    PENDING_HUMAN = "pending_human_review"
    HUMAN_REVIEWED = "human_reviewed"


class EvaluationTrack(str, Enum):
    SEARCH_API = "search_api"
    CONTEXT_SEARCH = "context_search"
    ANSWER_BEHAVIOR = "answer_behavior"


class ConstraintSupport(str, Enum):
    SUPPORTED = "supported"
    NOT_SUPPORTED = "not_supported"
    CONTRADICTED = "contradicted"


class EvidenceField(str, Enum):
    NAME = "name"
    DESCRIPTION = "description"
    REGION = "region"
    CITY = "city"
    CATEGORY = "category"


class Speaker(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"


ROOT = Path(__file__).resolve().parent
MINIMUM_RELEVANT_GRADE = Relevance.RELATED
RUNTIME_FIELDS = {"response", "retrieved_contexts", "execution", "ranking_comparison"}
ANSWERABILITY_BY_TYPE = {
    CaseType.INSUFFICIENT_EVIDENCE: Answerability.INSUFFICIENT_EVIDENCE,
    CaseType.CLARIFICATION_REQUIRED: Answerability.CLARIFICATION_REQUIRED,
}
CAPABILITIES_BY_CONDITION = {
    "city": "city_filter",
    "category": "category_filter",
    "area": "radius_filter",
    "exclude_place_ids": "place_exclusion",
    "conversation": "conversation_resolution",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path: Path, document: Any) -> None:
    path.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def digest_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def distance_meters(
    latitude: float,
    longitude: float,
    center: dict[str, float],
) -> float:
    latitude_delta = math.radians(latitude - center["latitude"])
    longitude_delta = math.radians(longitude - center["longitude"])
    haversine = (
        math.sin(latitude_delta / 2) ** 2
        + math.cos(math.radians(latitude))
        * math.cos(math.radians(center["latitude"]))
        * math.sin(longitude_delta / 2) ** 2
    )
    return 6_371_000 * 2 * math.asin(math.sqrt(min(1.0, haversine)))


def matches_conditions(
    place: dict[str, Any],
    conditions: dict[str, Any],
) -> bool:
    if place["id"] in conditions["exclude_place_ids"]:
        return False
    if any(
        conditions[field] is not None and place[field] != conditions[field]
        for field in ("region", "city", "category")
    ):
        return False
    area = conditions["area"]
    if area is None:
        return True
    if place["latitude"] is None or place["longitude"] is None:
        return False
    return distance_meters(
        place["latitude"],
        place["longitude"],
        area["center"],
    ) <= area["radius_meters"]


def sentence_excerpt(text: str, anchor: str) -> tuple[str, int, int]:
    start = text.find(anchor)
    require(start >= 0, f"Evidence anchor absent from source: {anchor!r}")
    # Offsets preserve the exported wording, including punctuation and whitespace.
    boundaries = list(re.finditer(r"(?<=[.!?])\s+|\n+", text))
    left = max((match.end() for match in boundaries if match.end() <= start), default=0)
    right = min(
        (match.start() for match in boundaries if match.start() >= start + len(anchor)),
        default=len(text),
    )
    return text[left:right], left, right


def build_evidence(
    place: dict[str, Any],
    anchors: list[str],
    place_index: int,
    raw_record: dict[str, Any],
    exported_at: str,
) -> list[dict[str, Any]]:
    evidence = [{
        "field": EvidenceField.NAME.value,
        "quote": place["name"],
        "json_pointer": f"/places/{place_index}/name",
    }]
    seen_spans: set[tuple[int, int]] = set()
    for anchor in anchors:
        quote, start, end = sentence_excerpt(place["description"] or "", anchor)
        if (start, end) in seen_spans:
            continue
        seen_spans.add((start, end))
        evidence.append({
            "field": EvidenceField.DESCRIPTION.value,
            "quote": quote,
            "char_start": start,
            "char_end": end,
            "json_pointer": f"/places/{place_index}/description",
        })
    evidence.extend({
        "field": field.value,
        "value": place[field.value],
        "json_pointer": f"/places/{place_index}/{field.value}",
    } for field in (EvidenceField.REGION, EvidenceField.CITY, EvidenceField.CATEGORY))
    return [{
        **item,
        "source_file": "snapshot.json",
        "source_table": "places",
        "source_provider": "TourAPI",
        "tour_content_id": place["tour_content_id"],
        "source_fetched_at": raw_record["fetched_at"],
        "snapshot_exported_at": exported_at,
    } for item in evidence]


def build_conditions(
    authored_case: dict[str, Any],
    places: dict[int, dict[str, Any]],
) -> dict[str, Any]:
    area = authored_case.get("area")
    resolved_area = None
    if area is not None:
        center_place = places[area["center_place_id"]]
        resolved_area = {
            **area,
            "center": {field: center_place[field] for field in ("latitude", "longitude")},
            "distance_method": "haversine_straight_line",
        }
    return {
        "region": authored_case.get("region", "서울"),
        "city": authored_case.get("city"),
        "category": authored_case.get("category"),
        "area": resolved_area,
        "exclude_place_ids": authored_case.get("exclude_place_ids", []),
        "conversation": [{
            "role": Speaker(role).value,
            "content": content,
        } for role, content in authored_case.get("conversation", [])],
    }


def evaluation_track(case: dict[str, Any]) -> str:
    if case["answerability"] != Answerability.ANSWERABLE:
        return EvaluationTrack.ANSWER_BEHAVIOR.value
    conditions = case["conditions"]
    if conditions["area"] or conditions["exclude_place_ids"] or conditions["conversation"]:
        return EvaluationTrack.CONTEXT_SEARCH.value
    return EvaluationTrack.SEARCH_API.value


def reference_documents(case: dict[str, Any]) -> list[dict[str, Any]]:
    positive_judgments = [
        judgment for judgment in case["judgments"]
        if judgment["relevance"] >= MINIMUM_RELEVANT_GRADE
    ]
    available = {
        item["place_id"]: item
        for item in [*case["judgments"], *case["reference_evidence"]]
    }
    ordered_ids = list(dict.fromkeys([
        *(judgment["place_id"] for judgment in positive_judgments),
        *(item["place_id"] for item in case["reference_evidence"]),
        *(place_id for judgment in positive_judgments for place_id in judgment.get("supporting_place_ids", [])),
    ]))
    require(set(ordered_ids) <= available.keys(), f"{case['case_id']}: reference context has no evidence")
    return [available[place_id] for place_id in ordered_ids]


def render_reference_context(document: dict[str, Any]) -> str:
    return "\n".join(
        item["quote"] if "quote" in item else f"{item['field']}: {item['value']}"
        for item in document["evidence"]
        if "quote" in item or "value" in item
    )


def build_case(
    *,
    authored_case: dict[str, Any],
    group: dict[str, Any],
    places: dict[int, dict[str, Any]],
    evidence_catalog: dict[int, list[dict[str, Any]]],
    snapshot_id: str,
    dataset_version: str,
) -> dict[str, Any]:
    case_type = CaseType(authored_case["case_type"])
    answerability = ANSWERABILITY_BY_TYPE.get(case_type, Answerability.ANSWERABLE)
    conditions = build_conditions(authored_case, places)
    judgments = [{
        **judgment,
        "relevance": Relevance(judgment["relevance"]).value,
        "semantic_constraint_support": judgment.get("semantic_constraint_support", {}),
        "name": places[judgment["place_id"]]["name"],
        "tour_content_id": places[judgment["place_id"]]["tour_content_id"],
        "has_embedding": places[judgment["place_id"]]["has_embedding"],
        "evidence": evidence_catalog[judgment["place_id"]],
    } for judgment in authored_case["judgments"]]
    relevant_ids = [
        judgment["place_id"] for judgment in judgments
        if judgment["relevance"] >= MINIMUM_RELEVANT_GRADE
    ]
    eligible_ids = [place_id for place_id, place in places.items() if matches_conditions(place, conditions)]
    reference_ids = authored_case.get("reference_place_ids", [])
    absence_check = authored_case.get("absence_check")
    capabilities = ["semantic_retrieval"]
    capabilities.extend(
        capability for field, capability in CAPABILITIES_BY_CONDITION.items()
        if conditions[field]
    )
    if answerability != Answerability.ANSWERABLE:
        capabilities.append("answerability_detection")
    known_issues = [
        {"place_id": place_id, "issue": "missing_embedding"}
        for place_id in relevant_ids if not places[place_id]["has_embedding"]
    ]
    known_issues.extend(
        {"place_id": place_id, "issue": "missing_city"}
        for place_id in relevant_ids if places[place_id]["city"] is None
    )
    case = {
        "case_id": f"TM-{group['group_id']}-{authored_case['case_suffix']:02d}",
        "dataset_version": dataset_version,
        "snapshot_id": snapshot_id,
        "split": Split(group["split"]).value,
        "group_id": group["group_id"],
        "case_type": case_type.value,
        "query": authored_case["query"],
        "reference": authored_case.get("reference"),
        "reference_provenance": authored_case.get("reference_provenance"),
        "conditions": conditions,
        "semantic_constraints": authored_case.get("semantic_constraints", []),
        "answerability": answerability.value,
        "expected_behavior": authored_case.get(
            "expected_action",
            "검색 조건을 지키며 근거가 있는 장소를 제시하고 추천 이유를 원문에 연결한다.",
        ),
        "missing_information": authored_case.get("missing_information", []),
        "judgment_scope": "partial_explicit_judgments",
        "unjudged_policy": "unjudged_is_not_irrelevant",
        "relevance_threshold": MINIMUM_RELEVANT_GRADE.value,
        "relevant_place_ids": relevant_ids,
        "strict_relevant_place_ids": [item["place_id"] for item in judgments if item["relevance"] == Relevance.DIRECT],
        "judgments": judgments,
        "reference_evidence": [{
            "place_id": place_id,
            "evidence": evidence_catalog[place_id],
        } for place_id in reference_ids],
        "absence_check": absence_check,
        "condition_check": {
            "corpus_place_count": len(places),
            "eligible_place_count": len(eligible_ids),
            "eligibility_includes_places_without_embeddings": True,
        },
        "required_facts": [{
            "place_id": judgment["place_id"],
            "fact": judgment["rationale"],
            "applies_when": "this_place_is_recommended",
        } for judgment in judgments if judgment["relevance"] >= Relevance.RELATED],
        "must_not_claim": [
            "DB 조회일을 실제 현장 정보의 최신성 보장으로 표현하지 않는다.",
            "조회한 원문에 없는 현재 영업·요금·예약·혼잡 상태를 확정하지 않는다.",
        ],
        "required_capabilities": capabilities,
        "known_corpus_issues": known_issues,
        "review": authored_case.get("review", {
            "author": "Codex",
            "status": ReviewStatus.PENDING_HUMAN.value,
            "human_reviewer": None,
            "human_reviewed_at": None,
            "evidence_validation": "exact_snapshot_match",
            "semantic_validation": "model_authored_not_independently_reviewed",
        }),
    }

    documents = reference_documents(case)
    case["reference_context_ids"] = [document["place_id"] for document in documents]
    case["reference_contexts"] = [render_reference_context(document) for document in documents]
    case["evaluation_track"] = evaluation_track(case)
    return case


def validate_snapshot(snapshot: dict[str, Any]) -> None:
    places = snapshot["places"]
    raw_records = snapshot["tour_api_raw"]
    require(len({place["id"] for place in places}) == len(places), "Duplicate snapshot place IDs")
    require(all(type(place["id"]) is int for place in places), "Place IDs must be integers")
    raw_ids = {record["tour_content_id"] for record in raw_records}
    require(len(raw_ids) == len(raw_records), "Duplicate raw content IDs")
    require(all(place["tour_content_id"] in raw_ids for place in places), "Missing TourAPI source")
    require(all(type(place["has_embedding"]) is bool for place in places), "Invalid embedding presence flag")


def validate_area(
    area: dict[str, Any] | None,
    places: dict[int, dict[str, Any]],
    case_id: str,
) -> None:
    if area is None:
        return
    require(area["center_place_id"] in places, f"{case_id}: unknown radius center")
    require(
        isinstance(area["radius_meters"], (int, float))
        and not isinstance(area["radius_meters"], bool)
        and math.isfinite(area["radius_meters"])
        and area["radius_meters"] > 0,
        f"{case_id}: invalid radius",
    )
    center_place = places[area["center_place_id"]]
    for field, maximum in [("latitude", 90), ("longitude", 180)]:
        value = area["center"][field]
        require(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value) and -maximum <= value <= maximum,
            f"{case_id}: invalid radius center coordinate",
        )
        require(value == center_place[field], f"{case_id}: center differs from snapshot")
    require(area["distance_method"] == "haversine_straight_line", f"{case_id}: unknown distance method")


def validate_evidence(
    reference: dict[str, Any],
    snapshot: dict[str, Any],
    places: dict[int, dict[str, Any]],
    raw_records: dict[str, dict[str, Any]],
    case_id: str,
) -> int:
    place = places[reference["place_id"]]
    require(bool(reference["evidence"]), f"{case_id}: empty evidence")
    for evidence in reference["evidence"]:
        field = EvidenceField(evidence["field"]).value
        source_value: Any = snapshot
        for part in evidence["json_pointer"].strip("/").split("/"):
            source_value = source_value[int(part)] if isinstance(source_value, list) else source_value[part]
        require(source_value == place[field], f"{case_id}: incorrect evidence pointer")
        if "char_start" in evidence:
            start, end = evidence["char_start"], evidence["char_end"]
            require(
                field == EvidenceField.DESCRIPTION and type(start) is int and type(end) is int
                and isinstance(source_value, str) and 0 <= start < end <= len(source_value),
                f"{case_id}: invalid evidence span",
            )
            require(source_value[start:end] == evidence["quote"], f"{case_id}: quote mismatch")
        elif "quote" in evidence:
            require(source_value == evidence["quote"], f"{case_id}: name mismatch")
        else:
            require(source_value == evidence["value"], f"{case_id}: metadata mismatch")
        expected_metadata = {
            "source_file": "snapshot.json",
            "source_table": "places",
            "source_provider": "TourAPI",
            "tour_content_id": place["tour_content_id"],
            "source_fetched_at": raw_records[place["tour_content_id"]]["fetched_at"],
            "snapshot_exported_at": snapshot["exported_at"],
        }
        require(
            all(evidence.get(key) == value for key, value in expected_metadata.items()),
            f"{case_id}: evidence provenance mismatch",
        )
    return len(reference["evidence"])


def referenced_place_ids(case: dict[str, Any]) -> set[int]:
    place_ids = {item["place_id"] for item in [*case["judgments"], *case["reference_evidence"]]}
    place_ids.update(case["conditions"]["exclude_place_ids"])
    if case["conditions"]["area"] is not None:
        place_ids.add(case["conditions"]["area"]["center_place_id"])
    for judgment in case["judgments"]:
        place_ids.update(judgment.get("supporting_place_ids", []))
    return place_ids


def validate_cases(
    cases: list[dict[str, Any]],
    snapshot: dict[str, Any],
    expected_count: int,
) -> dict[str, Any]:
    validate_snapshot(snapshot)
    places = {place["id"]: place for place in snapshot["places"]}
    raw_records = {record["tour_content_id"]: record for record in snapshot["tour_api_raw"]}
    require(expected_count > 0 and len(cases) == expected_count, "Unexpected case count")
    require(len({case["case_id"] for case in cases}) == len(cases), "Duplicate case IDs")
    require(len({case["query"].strip().casefold() for case in cases}) == len(cases), "Duplicate questions")
    group_splits: dict[str, set[str]] = {}
    judged_ids: set[int] = set()
    evidence_count = 0
    for case in cases:
        case_id = case["case_id"]
        require("reference" in case, f"{case_id}: reference field missing; rebuild JSONL from cases.source.json")
        reference_answer = case["reference"]
        require(
            reference_answer is None
            or (isinstance(reference_answer, str) and bool(reference_answer.strip())),
            f"{case_id}: reference must be a nonempty string or null when not authored",
        )
        case_type = CaseType(case["case_type"])
        expected_answerability = ANSWERABILITY_BY_TYPE.get(case_type, Answerability.ANSWERABLE)
        require(case["answerability"] == expected_answerability, f"{case_id}: answerability/type mismatch")
        Split(case["split"])
        status = ReviewStatus(case["review"]["status"])
        if status == ReviewStatus.HUMAN_REVIEWED:
            require(
                bool(case["review"]["human_reviewer"]) and bool(case["review"]["human_reviewed_at"]),
                f"{case_id}: reviewed label requires reviewer and date",
            )
        group_splits.setdefault(case["group_id"], set()).add(case["split"])
        require(not RUNTIME_FIELDS.intersection(case), f"{case_id}: system output in gold")
        require(case["evaluation_track"] == evaluation_track(case), f"{case_id}: evaluation track mismatch")
        require(case["relevance_threshold"] == MINIMUM_RELEVANT_GRADE, f"{case_id}: inconsistent relevance threshold")
        constraints = case["semantic_constraints"]
        constraint_ids = {constraint["id"] for constraint in constraints}
        require(len(constraint_ids) == len(constraints), f"{case_id}: duplicate semantic constraint")
        require(all(constraint["id"] and constraint["description"] for constraint in constraints), f"{case_id}: empty semantic constraint")
        conditions = case["conditions"]
        validate_area(conditions["area"], places, case_id)
        refs = referenced_place_ids(case)
        require(all(type(place_id) is int for place_id in refs) and refs <= places.keys(), f"{case_id}: unknown referenced place")
        judgments = case["judgments"]
        require(len({item["place_id"] for item in judgments}) == len(judgments), f"{case_id}: duplicate judgment")
        expected_relevant = []
        expected_strict = []
        grounded_ids = {item["place_id"] for item in [*judgments, *case["reference_evidence"]]}
        for judgment in judgments:
            place_id = judgment["place_id"]
            judged_ids.add(place_id)
            require(type(judgment["relevance"]) is int, f"{case_id}: grade must be an integer")
            grade = Relevance(judgment["relevance"])
            place = places[place_id]
            require(
                all(judgment[key] == place[key] for key in ("name", "tour_content_id", "has_embedding")),
                f"{case_id}: judgment identity mismatch",
            )
            assessments = judgment["semantic_constraint_support"]
            require(set(assessments) == constraint_ids, f"{case_id}: missing or unknown semantic assessment")
            for support in assessments.values():
                ConstraintSupport(support)
            if grade >= MINIMUM_RELEVANT_GRADE:
                require(all(value == ConstraintSupport.SUPPORTED for value in assessments.values()), f"{case_id}: relevant place lacks a required semantic condition")
                expected_relevant.append(place_id)
            if grade == Relevance.DIRECT:
                expected_strict.append(place_id)
            if grade > Relevance.IRRELEVANT:
                require(matches_conditions(place, conditions), f"{case_id}: positive violates conditions")
            require(
                set(judgment.get("supporting_place_ids", [])) <= grounded_ids,
                f"{case_id}: supporting place has no evidence in this case",
            )
        require(
            all(type(place_id) is int and place_id in places for place_id in case["relevant_place_ids"])
            and case["relevant_place_ids"] == expected_relevant,
            f"{case_id}: relevant_place_ids differ from threshold judgments",
        )
        require(case["strict_relevant_place_ids"] == expected_strict, f"{case_id}: strict relevant IDs mismatch")
        if case["answerability"] == Answerability.ANSWERABLE:
            require(bool(expected_relevant), f"{case_id}: answerable without relevant place")
        else:
            require(not expected_relevant, f"{case_id}: diagnostic case has relevant places")
            require(bool(case["missing_information"]), f"{case_id}: missing diagnostic reason")
        expected_eligible_count = sum(matches_conditions(place, conditions) for place in places.values())
        require(
            case["condition_check"]["corpus_place_count"] == len(places)
            and case["condition_check"]["eligible_place_count"] == expected_eligible_count
            and case["condition_check"]["eligibility_includes_places_without_embeddings"] is True,
            f"{case_id}: stale corpus/eligible place count",
        )
        for reference in [*judgments, *case["reference_evidence"]]:
            evidence_count += validate_evidence(reference, snapshot, places, raw_records, case_id)
        documents = reference_documents(case)
        require(
            case.get("reference_context_ids") == [document["place_id"] for document in documents]
            and case.get("reference_contexts") == [render_reference_context(document) for document in documents],
            f"{case_id}: reference contexts differ from positive/supporting source evidence",
        )
        if case["absence_check"] is not None:
            absence = case["absence_check"]
            matches = sum(place[absence["field"]] == absence["value"] for place in places.values())
            require(matches == absence["expected_matches"] == 0, f"{case_id}: asserted absence is false")
            require(expected_eligible_count == 0, f"{case_id}: absent-region case has eligible records")
    require(all(len(splits) == 1 for splits in group_splits.values()), "Question family split leakage")
    return {
        "status": "passed",
        "case_count": len(cases),
        "evidence_items_checked": evidence_count,
        "judgment_count": sum(len(case["judgments"]) for case in cases),
        "judged_places": len(judged_ids),
        "counts_by_split": dict(Counter(case["split"] for case in cases)),
        "counts_by_case_type": dict(Counter(case["case_type"] for case in cases)),
        "counts_by_answerability": dict(Counter(case["answerability"] for case in cases)),
        "counts_by_evaluation_track": dict(Counter(case["evaluation_track"] for case in cases)),
        "reference_count": sum(case["reference"] is not None for case in cases),
        "missing_reference_count": sum(case["reference"] is None for case in cases),
        "reference_context_case_count": sum(bool(case["reference_contexts"]) for case in cases),
        "reference_context_count": sum(len(case["reference_contexts"]) for case in cases),
        "answerable_missing_reference_count": sum(
            case["answerability"] == Answerability.ANSWERABLE and case["reference"] is None
            for case in cases
        ),
        "checks": [
            "unique_case_ids_and_queries", "all_place_ids_and_threshold_sets_match",
            "exact_evidence_offsets_identity_and_provenance", "all_eligible_counts_recalculated",
            "positive_judgments_respect_filters_radius_and_exclusions",
            "semantic_requirement_annotations_are_consistent_not_automatically_proven",
            "absence_checked_against_entire_corpus", "no_question_group_crosses_splits",
            "evaluation_tracks_match_supported_inputs", "no_system_outputs_in_gold",
            "reference_is_authored_text_or_explicitly_missing",
            "reference_contexts_match_positive_and_supporting_source_evidence",
        ],
        "human_review_completed": all(case["review"]["status"] == ReviewStatus.HUMAN_REVIEWED for case in cases),
        "retrieval_or_generation_evaluation_run": False,
    }


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows),
        encoding="utf-8",
        newline="\n",
    )


def render_csv(columns: list[str], rows: list[dict[str, Any]]) -> bytes:
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return ("\ufeff" + stream.getvalue()).encode("utf-8")


def render_review_sheet(cases: list[dict[str, Any]]) -> bytes:
    columns = [
        "case_id", "split", "evaluation_track", "query", "conditions", "semantic_constraints",
        "answerability", "place_id", "place_name", "relevance", "semantic_constraint_support",
        "rationale_or_expected_behavior", "evidence", "review_status", "human_reviewer", "review_notes",
    ]
    rows = []
    for case in cases:
        for judgment in case["judgments"] or [{}]:
            rows.append({
                "case_id": case["case_id"], "split": case["split"], "evaluation_track": case["evaluation_track"],
                "query": case["query"], "conditions": json.dumps(case["conditions"], ensure_ascii=False),
                "semantic_constraints": json.dumps(case["semantic_constraints"], ensure_ascii=False),
                "answerability": case["answerability"], "place_id": judgment.get("place_id", ""),
                "place_name": judgment.get("name", ""), "relevance": judgment.get("relevance", ""),
                "semantic_constraint_support": json.dumps(judgment.get("semantic_constraint_support", {}), ensure_ascii=False),
                "rationale_or_expected_behavior": judgment.get("rationale", case["expected_behavior"]),
                "evidence": "\n".join(item["quote"] for item in judgment.get("evidence", []) if "quote" in item),
                "review_status": case["review"]["status"],
                "human_reviewer": case["review"].get("human_reviewer") or "", "review_notes": "",
            })
    return render_csv(columns, rows)


def write_review_sheet(path: Path, cases: list[dict[str, Any]]) -> None:
    path.write_bytes(render_review_sheet(cases))


def render_corpus_sheet(places: list[dict[str, Any]]) -> bytes:
    columns = [
        "id", "tour_content_id", "name", "region", "city", "category", "source_category",
        "latitude", "longitude", "has_embedding", "description",
    ]
    return render_csv(columns, places)


def write_corpus_sheet(path: Path, places: list[dict[str, Any]]) -> None:
    path.write_bytes(render_corpus_sheet(places))


def assemble_cases(
    snapshot: dict[str, Any],
    authored: dict[str, Any],
    snapshot_id: str,
) -> list[dict[str, Any]]:
    validate_snapshot(snapshot)
    places = {place["id"]: place for place in snapshot["places"]}
    raw_records = {record["tour_content_id"]: record for record in snapshot["tour_api_raw"]}
    anchors = {
        int(place_id): snippets
        for group in authored["groups"] for place_id, snippets in group["evidence_anchors"].items()
    }
    evidence_catalog = {
        place["id"]: build_evidence(
            place,
            anchors[place["id"]],
            index,
            raw_records[place["tour_content_id"]],
            snapshot["exported_at"],
        )
        for index, place in enumerate(snapshot["places"]) if place["id"] in anchors
    }
    cases = [build_case(
        authored_case=authored_case,
        group=group,
        places=places,
        evidence_catalog=evidence_catalog,
        snapshot_id=snapshot_id,
        dataset_version=authored["dataset_version"],
    ) for group in authored["groups"] for authored_case in group["cases"]]
    return cases


def build(root: Path) -> dict[str, Any]:
    snapshot_path = root / "snapshot.json"
    source_path = root / "cases.source.json"
    snapshot = read_json(snapshot_path)
    authored = read_json(source_path)
    snapshot_id = "sha256:" + digest_file(snapshot_path)
    cases = assemble_cases(snapshot, authored, snapshot_id)
    validation = validate_cases(cases, snapshot, authored["expected_case_count"])
    validation["snapshot_id"] = snapshot_id
    validation["dataset_version"] = authored["dataset_version"]
    write_jsonl(root / "golden.jsonl", cases)
    for split in Split:
        write_jsonl(root / f"{split.value}.jsonl", [case for case in cases if case["split"] == split])
    for track in EvaluationTrack:
        write_jsonl(root / f"{track.value}.jsonl", [case for case in cases if case["evaluation_track"] == track])
    write_json(root / "corpus.json", snapshot["places"])
    write_corpus_sheet(root / "places.csv", snapshot["places"])
    write_review_sheet(root / "review.csv", cases)
    write_json(root / "development_run.json", {"status": "not_run", "case_count": 0})
    write_jsonl(root / "api_embedding" / "v1.jsonl", [])
    write_json(root / "api_embedding" / "fastapi_embed_smoke.json", {"status": "not_run"})
    write_jsonl(root / "api_reranking" / "v2.jsonl", [])
    write_jsonl(root / "ragas_results.jsonl", [])
    write_json(root / "ragas_summary.json", {"status": "not_run", "score_count": 0})
    write_json(root / "ragas_llm_precheck.json", {
        "status": "not_run",
        "metric_family": "reference_based_llm",
        "score_count": 0,
    })
    write_jsonl(root / "ranking_results.jsonl", [])
    write_json(root / "ranking_summary.json", {"status": "not_run", "case_count": 0})
    for cutoff in (5, 10):
        ranking_dir = root / f"ranking_at_{cutoff}"
        ranking_dir.mkdir(parents=True, exist_ok=True)
        write_jsonl(ranking_dir / "results.jsonl", [])
        write_json(ranking_dir / "summary.json", {"status": "not_run", "case_count": 0, "cutoff": cutoff})
        (ranking_dir / "run.log").write_text("", encoding="utf-8", newline="\n")
    write_json(root / "validation.json", validation)
    write_json(root / "manifest.json", build_manifest(root, snapshot, authored, cases, validation))
    return validation


def build_manifest(
    root: Path,
    snapshot: dict[str, Any],
    authored: dict[str, Any],
    cases: list[dict[str, Any]],
    validation: dict[str, Any],
) -> dict[str, Any]:
    artifacts = [
        "golden.jsonl", "development.jsonl", "test.jsonl", "corpus.json", "places.csv",
        "review.csv", "validation.json", "development_run.json", "api_embedding/v1.jsonl",
        "api_embedding/fastapi_embed_smoke.json",
        "api_reranking/v2.jsonl", "ragas_results.jsonl",
        "ragas_summary.json", "ragas_llm_precheck.json",
        "ranking_results.jsonl", "ranking_summary.json",
        "ranking_at_5/results.jsonl", "ranking_at_5/summary.json",
        "ranking_at_5/run.log",
        "ranking_at_10/results.jsonl", "ranking_at_10/summary.json",
        "ranking_at_10/run.log",
    ]
    artifacts.extend(f"{track.value}.jsonl" for track in EvaluationTrack)
    development_cases = [
        json.loads(line)
        for line in (root / "development.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    return {
        "dataset_name": "TravelMate Seoul place search golden candidate set",
        "dataset_version": authored["dataset_version"],
        "schema_version": authored["schema_version"],
        "snapshot_id": "sha256:" + digest_file(root / "snapshot.json"),
        "snapshot_exported_at": snapshot["exported_at"],
        "database": snapshot["database"],
        "places_count": len(snapshot["places"]),
        "raw_records_count": len(snapshot["tour_api_raw"]),
        "export_scope": "all_places_and_all_tour_api_raw_rows",
        "omitted_columns": ["places.embedding vector values; has_embedding retained"],
        "source_of_truth": "snapshot.json",
        "authoring_source": "cases.source.json",
        "authoring_sha256": digest_file(root / "cases.source.json"),
        "golden_sha256": digest_file(root / "golden.jsonl"),
        "artifact_sha256": {name: digest_file(root / name) for name in artifacts},
        "builder_sha256": digest_file(root / "build_dataset.py"),
        "case_count": len(cases),
        "counts_by_split": validation["counts_by_split"],
        "counts_by_case_type": validation["counts_by_case_type"],
        "counts_by_answerability": validation["counts_by_answerability"],
        "counts_by_evaluation_track": validation["counts_by_evaluation_track"],
        "reference_count": validation["reference_count"],
        "missing_reference_count": validation["missing_reference_count"],
        "reference_context_case_count": validation["reference_context_case_count"],
        "reference_context_count": validation["reference_context_count"],
        "answerable_missing_reference_count": validation["answerable_missing_reference_count"],
        "actual_execution_counts": dict(Counter(
            case.get("execution", {}).get("status", "not_run") for case in development_cases
        )),
        "ragas_status": read_json(root / "ragas_summary.json")["status"],
        "corpus_regions": dict(Counter(place["region"] for place in snapshot["places"])),
        "corpus_categories": dict(Counter(place["category"] for place in snapshot["places"])),
        "missing_embedding_place_ids": [place["id"] for place in snapshot["places"] if not place["has_embedding"]],
        "missing_city_place_ids": [place["id"] for place in snapshot["places"] if place["city"] is None],
        "relevance_scale": {
            "3": "핵심 의도와 모든 명시 필수 조건을 직접 충족",
            "2": "필수 조건이 근거로 확인되나 직접성·시설 범위가 낮은 유용한 대안; 동일 시설 상위 공간은 관계 근거 필요",
            "1": "주제만 일부 관련되거나 필수 조건이 미확인; 정답에서 제외",
            "0": "의도 불일치 또는 명시 조건 위반",
        },
        "annotation_policy": authored["annotation_policy"],
        "reference_authoring": authored.get("reference_authoring"),
        "revision_review": authored["revision_review"],
        "unjudged_policy": "미판정 장소를 0점으로 간주하지 않는다. 전수 관련도 판정이 아니다.",
        "review_status": ReviewStatus.HUMAN_REVIEWED.value if validation["human_review_completed"] else ReviewStatus.PENDING_HUMAN.value,
        "split_policy": "질문·유사 의도 그룹(group_id)을 분할 간 분리한다. 같은 장소가 다른 그룹 질문의 정답·근거로 등장하는 것은 허용한다.",
        "line_endings": {"generated_json_jsonl_csv": "LF", "snapshot": "original bytes preserved; Git -text"},
        "limitations": [
            (
                "사용자가 기존 판정의 사람 검수 완료를 확인했다. 미판정 후보는 검수 범위에 포함되지 않는다."
                if validation["human_review_completed"]
                else "AI의 원문 대조 후 수정했으며 독립적인 사람 검수는 아직 없다."
            ),
            "인용 일치와 의미 조건 주석의 일관성 검증은 의미적 타당성의 자동 증명이 아니다.",
            "미판정 관련 장소가 남아 있을 수 있다. 여러 검색기 결과 pool을 검수해야 한다.",
            "서울 코퍼스만 평가하며 시험 검색 문항은 16개·주제 그룹은 4개다.",
            "장소 ID는 분할 간에 겹칠 수 있다. 개발셋으로 장소별 규칙을 튜닝하면 시험 점수가 낙관적으로 나올 수 있다.",
            "반경 문항은 후보가 한 개뿐인 필터 확인 시험이며 경계·순위 시험은 보완이 필요하다.",
            "TourAPI 수집일은 현장 상태의 최신성 보장이 아니다. 실제 검색·RAGAS 점수는 산출하지 않았다.",
        ],
    }


def check(root: Path, *, require_reference: bool = False) -> dict[str, Any]:
    snapshot = read_json(root / "snapshot.json")
    authored = read_json(root / "cases.source.json")
    manifest = read_json(root / "manifest.json")
    cases = [json.loads(line) for line in (root / "golden.jsonl").read_text(encoding="utf-8").splitlines()]
    snapshot_id = "sha256:" + digest_file(root / "snapshot.json")
    require(manifest["snapshot_id"] == snapshot_id, "Snapshot digest mismatch")
    require(manifest["golden_sha256"] == digest_file(root / "golden.jsonl"), "Golden digest mismatch")
    require(manifest["authoring_sha256"] == digest_file(root / "cases.source.json"), "Authoring digest mismatch")
    require(all(case["snapshot_id"] == snapshot_id for case in cases), "Case snapshot mismatch")
    require(all(case["dataset_version"] == authored["dataset_version"] for case in cases), "Case version mismatch")
    validation = validate_cases(cases, snapshot, authored["expected_case_count"])
    validation["snapshot_id"] = snapshot_id
    validation["dataset_version"] = authored["dataset_version"]
    require(cases == assemble_cases(snapshot, authored, snapshot_id), "Golden differs from authoring source")
    require(read_json(root / "corpus.json") == snapshot["places"], "Corpus export mismatch")
    for field, values in [("split", Split), ("evaluation_track", EvaluationTrack)]:
        for value in values:
            exported = [json.loads(line) for line in (root / f"{value.value}.jsonl").read_text(encoding="utf-8").splitlines()]
            expected = [case for case in cases if case[field] == value]
            if field == "split" and value == Split.DEVELOPMENT:
                require(len(exported) == len(expected), "development: export count mismatch")
                for stored_case, expected_case in zip(exported, expected, strict=True):
                    require(
                        {key: item for key, item in stored_case.items() if key not in RUNTIME_FIELDS}
                        == expected_case,
                        f"{stored_case['case_id']}: development differs from authored case",
                    )
                    validate_runtime_output(stored_case)
            else:
                require(exported == expected, f"{value}: export mismatch")
    require((root / "places.csv").read_bytes() == render_corpus_sheet(snapshot["places"]), "Corpus CSV mismatch")
    require((root / "review.csv").read_bytes() == render_review_sheet(cases), "Review CSV mismatch; merge notes into source before rebuilding")
    require(read_json(root / "validation.json") == validation, "Validation report mismatch")
    require(manifest == build_manifest(root, snapshot, authored, cases, validation), "Manifest metadata/digest mismatch")
    if require_reference:
        missing_references = [
            case["case_id"] for case in cases
            if case["answerability"] == Answerability.ANSWERABLE and case["reference"] is None
        ]
        require(
            not missing_references,
            f"{len(missing_references)} answerable cases lack reference; "
            "author expected answers in cases.source.json and rebuild JSONL. "
            f"Missing case IDs: {', '.join(missing_references)}",
        )
    return validation


def validate_runtime_output(case: dict[str, Any]) -> None:
    runtime_fields = RUNTIME_FIELDS.intersection(case)
    if not runtime_fields:
        return
    require(runtime_fields == RUNTIME_FIELDS, f"{case['case_id']}: incomplete runtime fields")
    require(isinstance(case["retrieved_contexts"], list), f"{case['case_id']}: retrieved_contexts must be a list")
    execution = case["execution"]
    comparison = case["ranking_comparison"]
    for version, variant in comparison.items():
        duration = variant.get("execution", {}).get("duration_seconds")
        require(
            duration is None or isinstance(duration, (int, float)) and duration >= 0,
            f"{case['case_id']}: invalid duration for {version}",
        )
    if execution["status"] == "completed":
        require(isinstance(case["response"], str), f"{case['case_id']}: completed execution requires response")
        require(
            execution["response_field_source"] == "target_system_http_response",
            f"{case['case_id']}: response is not a target system output",
        )
        response_places = json.loads(case["response"])
        require(isinstance(response_places, list), f"{case['case_id']}: response must be a JSON array")
        returned_contexts = [place.get("description") or "" for place in response_places]
        require(returned_contexts == case["retrieved_contexts"], f"{case['case_id']}: contexts differ from target output")
        require(
            set(comparison) == {"v1_semantic_only", "v2_reranked"},
            f"{case['case_id']}: missing ranking version",
        )
        for variant in comparison.values():
            require(isinstance(variant.get("response"), str), f"{case['case_id']}: ranking variant response missing")
            variant_places = json.loads(variant["response"])
            require(isinstance(variant_places, list), f"{case['case_id']}: ranking variant response must be a JSON array")
            require(
                [place["placeId"] for place in variant_places] == variant["place_ids"],
                f"{case['case_id']}: ranking variant place IDs differ from response",
            )
    else:
        require(case["response"] is None and not case["retrieved_contexts"], f"{case['case_id']}: output without execution")


def refresh_runtime_exports(root: Path, run_summary: dict[str, Any] | None = None) -> dict[str, Any]:
    snapshot = read_json(root / "snapshot.json")
    authored = read_json(root / "cases.source.json")
    snapshot_id = "sha256:" + digest_file(root / "snapshot.json")
    golden_cases = [
        json.loads(line)
        for line in (root / "golden.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    development_cases = [
        json.loads(line)
        for line in (root / "development.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    require(
        len(development_cases) == len([case for case in golden_cases if case["split"] == Split.DEVELOPMENT]),
        "development runtime export has an unexpected case count",
    )
    expected_development = [case for case in golden_cases if case["split"] == Split.DEVELOPMENT]
    for case, expected_case in zip(development_cases, expected_development, strict=True):
        require(
            {key: value for key, value in case.items() if key not in RUNTIME_FIELDS} == expected_case,
            f"{case['case_id']}: runtime output modified an authored field",
        )
        validate_runtime_output(case)
    validation = validate_cases(golden_cases, snapshot, authored["expected_case_count"])
    validation["snapshot_id"] = snapshot_id
    validation["dataset_version"] = authored["dataset_version"]
    if run_summary is not None:
        write_json(root / "development_run.json", run_summary)
    write_json(root / "validation.json", validation)
    write_json(root / "manifest.json", build_manifest(root, snapshot, authored, golden_cases, validation))
    return validation


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--check", action="store_true", help="Validate existing files without overwriting them")
    parser.add_argument(
        "--require-reference",
        action="store_true",
        help="With --check, also require an authored reference for every answerable case",
    )
    arguments = parser.parse_args()
    if arguments.require_reference and not arguments.check:
        parser.error("--require-reference requires --check")
    if arguments.check:
        print(json.dumps(check(arguments.root, require_reference=arguments.require_reference), ensure_ascii=False, indent=2))
        return
    print(json.dumps(build(arguments.root), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
