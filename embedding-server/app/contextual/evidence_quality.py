"""장소 순위를 유지하며 연결 근거의 대표 선택·불확실성·보류를 처리한다."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, replace
from enum import StrEnum
import json
import re
from typing import Any

from .connection_statements import StatementAssessment, StatementStatus, TravelMode, assess_statement
from .contracts import ContentKind
from .observation_search import ObservationFilter
from .relations import RelationType, RetrievalScope


class RequirementScope(StrEnum):
    CONNECTION = "connection"
    OTHER = "not_assessed"
    UNRESOLVED = "question_requirement_unresolved"


class DecisionStatus(StrEnum):
    REPORTED = "reported_connection"
    CONFLICT = "conflicting_reports"
    WITHHELD = "withheld"


class WithholdingReason(StrEnum):
    NO_RELATION = "no_verified_connection_evidence"
    NO_POSITIVE = "no_positive_connection_evidence"
    UNASSESSED = "connection_statement_unassessed"
    MODE = "requested_travel_mode_not_supported"
    SNAPSHOT = "active_evidence_snapshot_changed"
    QUESTION = "question_requirement_unresolved"


class ContextCoverage(StrEnum):
    ACTIVE = "active_snapshot"
    SELECTED = "selected_evidence_only"
    CHANGED = "snapshot_changed"


class AccessibilityState(StrEnum):
    UNVERIFIED = "unverified"


CONNECTION_QUESTION = re.compile(r"(?:연결|이어(?:진|져)|(?:다른|다음|인근).*(?:이동|걸어|도보)|(?:에서|으로|까지).*(?:걸어|도보|이동))")
AMBIGUOUS_QUESTION = re.compile(r"(?:상관없|필요\s*없|원하지|싫|연결[^.!?]*(?:없|않))")


@dataclass(frozen=True)
class QuestionRequirement:
    scope: RequirementScope
    mode: TravelMode = TravelMode.ANY
    observation: ObservationFilter | None = None


@dataclass(frozen=True)
class EvidenceContext:
    documents: tuple[dict[str, Any], ...]
    coverage: ContextCoverage


@dataclass(frozen=True)
class RelationFinding:
    document: dict[str, Any]
    relation_index: int
    assessment: StatementAssessment
    rerank_score: float | None = None

    @property
    def relation(self) -> dict[str, Any]:
        return self.document["relations"][self.relation_index]

    @property
    def edge(self) -> tuple[Any, ...]:
        relation = self.relation
        return tuple(
            ("place_id", relation[side]["place_id"])
            if relation[side].get("place_id") is not None
            else ("name", relation[side]["name"])
            for side in ("origin", "destination")
        )

    @property
    def key(self) -> tuple[Any, ...]:
        return self.document["chunk_id"], self.document["context_version"], self.relation_index

    def reference(self) -> dict[str, Any]:
        relation = self.relation
        return {
            "chunk_id": self.document["chunk_id"],
            "context_version": self.document["context_version"],
            "source_id": self.document["source_id"],
            "source_version": self.document["source_version"],
            "source_url": self.document.get("metadata", {}).get("source_url"),
            "source_span": deepcopy(self.document["source_span"]),
            "place_refs": deepcopy(self.document["place_refs"]),
            "relation_index": self.relation_index,
            "type": relation["type"],
            "importance": relation["importance"],
            "origin": deepcopy(relation["origin"]),
            "destination": deepcopy(relation["destination"]),
            "conditions": deepcopy(relation["conditions"]),
            "evidence": deepcopy(relation["evidence"]),
            "statement_status": self.assessment.status,
            "travel_mode": self.assessment.mode,
            "rerank_score": self.rerank_score,
            "published_at": self.document.get("metadata", {}).get("published_at"),
            "current_accessibility": AccessibilityState.UNVERIFIED,
        }


@dataclass(frozen=True)
class QualityBatch:
    accepted: list[tuple[dict[str, Any], float | None]]
    withheld: list[dict[str, Any]]
    requirement: QuestionRequirement


def question_requirement(
    query: str,
    observation: ObservationFilter | None,
) -> QuestionRequirement:
    if observation is not None and not observation.includes_relations:
        return QuestionRequirement(RequirementScope.OTHER)
    if observation is None and not CONNECTION_QUESTION.search(query):
        return QuestionRequirement(RequirementScope.OTHER)
    walking = bool(re.search(r"(?:도보|걸어|걸을)", query))
    vehicle = bool(re.search(r"(?:차량|자동차|버스|택시)", query))
    if AMBIGUOUS_QUESTION.search(query) or (walking and vehicle):
        return QuestionRequirement(RequirementScope.UNRESOLVED, observation=observation)
    modes = [mode for mode, present in ((TravelMode.WALKING, walking), (TravelMode.VEHICLE, vehicle)) if present]
    return QuestionRequirement(
        scope=RequirementScope.CONNECTION,
        mode=modes[0] if modes else TravelMode.ANY,
        observation=observation,
    )


def _document(value: Any) -> dict[str, Any] | None:
    return json.loads(value) if isinstance(value, str) else value


def relation_findings(
    place_id: int,
    document: dict[str, Any],
    requirement: QuestionRequirement,
    *,
    rerank_score: float | None = None,
) -> list[RelationFinding]:
    observation = requirement.observation or ObservationFilter(content_kinds=(ContentKind.MOVEMENT,))
    allowed = observation.matched_relations(place_id, document)
    selected = document.get("matched_relations", allowed)
    result = []
    for index, relation in enumerate(document.get("relations", [])):
        if relation not in allowed or relation not in selected:
            continue
        retrieved_index = document.get("retrieved_relation_index", index)
        if retrieved_index != index:
            continue
        evidence = relation.get("evidence")
        if not evidence or relation.get("type") != RelationType.MOVEMENT:
            continue
        span = document["source_span"]
        start, end = evidence["start"], evidence["end"]
        if (type(start) is not int or type(end) is not int
                or not span["start"] <= start < end <= span["end"]
                or document["chunk_text"][start - span["start"]:end - span["start"]] != evidence["quote"]):
            raise ValueError("연결 판정의 원문 위치와 인용이 다릅니다")
        result.append(RelationFinding(
            document=document,
            relation_index=index,
            assessment=assess_statement(evidence["quote"]),
            rerank_score=rerank_score,
        ))
    return result


def _matches_mode(finding: RelationFinding, mode: TravelMode) -> bool:
    return mode == TravelMode.ANY or finding.assessment.mode == mode


def _conflicts(positive: RelationFinding, other: RelationFinding) -> bool:
    return (positive.edge == other.edge and other.assessment.status == StatementStatus.BLOCKED
            and (TravelMode.UNSPECIFIED in (positive.assessment.mode, other.assessment.mode)
                 or positive.assessment.mode == other.assessment.mode))


def _finding_text(finding: RelationFinding) -> str:
    relation = finding.relation
    return f"출발지: {relation['origin']['name']} → 도착지: {relation['destination']['name']}\n{relation['evidence']['quote']}"


def _selected_documents(row: dict[str, Any]) -> list[dict[str, Any]]:
    documents = row.get("reranked_evidence_chunks")
    if documents is not None:
        return documents
    primary = _document(row.get("evidence"))
    return [primary] if primary else []


def apply_connection_quality(
    ranked: list[tuple[dict[str, Any], float | None]],
    requirement: QuestionRequirement,
    contexts: dict[int, EvidenceContext],
) -> QualityBatch:
    if requirement.scope == RequirementScope.OTHER:
        return QualityBatch(ranked, [], requirement)
    accepted = []
    withheld = []
    for original_rank, (row, score) in enumerate(ranked, 1):
        documents = _selected_documents(row)
        context = contexts.get(row["place_id"], EvidenceContext(tuple(documents), ContextCoverage.SELECTED))
        reason = None
        if requirement.scope == RequirementScope.UNRESOLVED:
            reason = WithholdingReason.QUESTION
        if context.coverage == ContextCoverage.CHANGED:
            reason = WithholdingReason.SNAPSHOT
        findings = [
            finding for document in documents
            for finding in relation_findings(
                row["place_id"],
                document,
                requirement,
                rerank_score=document.get("rerank_score", score),
            )
        ]
        context_observation = requirement.observation
        if context_observation is not None:
            context_observation = replace(context_observation, relation_importance=())
        context_requirement = QuestionRequirement(RequirementScope.CONNECTION, requirement.mode, context_observation)
        all_findings = [
            finding for document in context.documents
            for finding in relation_findings(row["place_id"], document, context_requirement)
        ]
        positive = [finding for finding in findings if finding.assessment.status == StatementStatus.POSITIVE]
        eligible = [finding for finding in positive if _matches_mode(finding, requirement.mode)]
        if reason is None and not findings:
            reason = WithholdingReason.NO_RELATION
        if reason is None and not eligible:
            reason = WithholdingReason.NO_POSITIVE
            if positive:
                reason = WithholdingReason.MODE
            if any(finding.assessment.status == StatementStatus.UNKNOWN for finding in findings):
                reason = WithholdingReason.UNASSESSED
        if reason is not None:
            withheld.append({
                "place_id": row["place_id"],
                "original_rank": original_rank,
                "ranking_score": score,
                "status": DecisionStatus.WITHHELD,
                "reason": reason,
                "evidence_chunks": deepcopy(documents),
                "assessed_relations": [finding.reference() for finding in findings],
                "active_relation_context": [finding.reference() for finding in all_findings],
                "context_coverage": context.coverage,
            })
            continue
        winner = max(eligible, key=lambda finding: finding.rerank_score if finding.rerank_score is not None else float("-inf"))
        blocking = list({finding.key: finding for finding in all_findings if _conflicts(winner, finding)}.values())
        unresolved = list({finding.key: finding for finding in all_findings if finding.assessment.status == StatementStatus.UNKNOWN}.values())
        notes = ["원문에 기록된 이동 정보이며 현재 통행 가능 여부는 확인하지 않았습니다."]
        if blocking:
            notes = ["이동 성공 기록과 통행 차단 기록의 시점 관계가 불명확해 현재 이동 가능 여부를 확정할 수 없습니다."]
        if unresolved:
            notes.append("판정하지 못한 관련 이동 기록도 있습니다.")
        if context.coverage == ContextCoverage.SELECTED:
            notes.append("선택된 근거 범위만 확인했습니다.")
        description = _finding_text(winner) + "\n\n" + "\n".join(notes)
        if blocking:
            description += "\n\n통행 차단 기록\n" + "\n".join(_finding_text(finding) for finding in blocking)
        representative = deepcopy(winner.document)
        representative.update({
            "retrieval_scope": RetrievalScope.RELATION,
            "matched_relations": [deepcopy(winner.relation)],
            "representative_relation_index": winner.relation_index,
        })
        ordered_documents = sorted(documents, key=lambda document: document is not winner.document)
        accepted.append(({**row,
            "description": description,
            "evidence": representative,
            "reranked_evidence_chunks": deepcopy(ordered_documents),
            "evidence_assessment": {
                "status": DecisionStatus.CONFLICT if blocking else DecisionStatus.REPORTED,
                "assessed_requirement": RequirementScope.CONNECTION,
                "current_accessibility": AccessibilityState.UNVERIFIED,
                "context_coverage": context.coverage,
                "original_rank": original_rank,
                "ranking_score": score,
                "representative_rerank_score": winner.rerank_score,
                "positive_evidence": [finding.reference() for finding in eligible],
                "blocking_evidence": [finding.reference() for finding in blocking],
                "unassessed_evidence": [finding.reference() for finding in unresolved],
            }}, score))
    return QualityBatch(accepted, withheld, requirement)
