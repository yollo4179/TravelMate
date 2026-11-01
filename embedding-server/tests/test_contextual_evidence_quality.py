"""연결 근거의 긍정·차단·미판정과 점수 독립적인 결과 보류를 검증한다."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
import sys
from typing import Any
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.connection_statements import StatementStatus, TravelMode, assess_statement
from app.contextual.contracts import SearchChunk, SplitterVersion
from app.contextual.evidence_quality import (
    ContextCoverage,
    DecisionStatus,
    EvidenceContext,
    RequirementScope,
    WithholdingReason,
    apply_connection_quality,
    question_requirement,
)
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import normalize_source
from app.enrichment.contracts import fingerprint

WALK = "출발공원에서 계단을 내려가 도착공원까지 걸어갔다."
BLOCK = "출발공원에서 도착공원으로 이동하려 했지만 공사로 길이 막혀 돌아왔다."
VEHICLE = "도착공원까지 차량으로만 이동할 수 있으며 도보 통행은 금지된다."


def document(
    quote: str,
    *,
    origin: int = 901,
    destination: int = 902,
    importance: str = "primary",
    conditions: tuple[str, ...] = (),
    relation: bool = True,
) -> dict[str, Any]:
    source = normalize_source({
        "source_type": "review",
        "title": "근거 품질 검사",
        "text": quote,
        "metadata": {"source_url": "https://example.org/quality/" + fingerprint([quote, origin, destination]), "capture_scope": "full_text"},
    })
    relations = [{
        "type": "movement",
        "importance": importance,
        "origin": {"place_id": origin, "name": "출발공원"},
        "destination": {"place_id": destination, "name": "도착공원"},
        "conditions": [{"kind": "other", "quote": condition} for condition in conditions],
        "evidence": {"start": 0, "end": len(quote), "quote": quote},
    }] if relation else []
    chunk = SearchChunk(
        source=source,
        start=0,
        end=len(quote),
        context_text="원문을 보존한 검사용 이동 기록이다.",
        place_refs=[{"place_id": origin, "role": "subject"}, {"place_id": destination, "role": "mentioned"}],
        generation={"provider": "synthetic-quality-test"},
        splitter_version=SplitterVersion.SENTENCE,
        content_kind="other",
        relations=relations,
    )
    return {**chunk.to_dict(), "context_version": chunk.context_version}


def candidate(
    place_id: int,
    documents: list[dict[str, Any]],
    scores: list[float],
) -> dict[str, Any]:
    return {
        "place_id": place_id,
        "source_version": 7,
        "semantic_score": 0.1,
        "description": documents[0]["chunk_text"],
        "evidence": documents[0],
        "reranked_evidence_chunks": [
            {**entry, "rerank_score": score, "semantic_score": 0.1}
            for entry, score in zip(documents, scores, strict=True)
        ],
    }


class EvidenceQualityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.requirement = question_requirement("주변 관광지와 연결된 곳", None)

    def test_vehicle_restriction_is_not_misread_as_total_blockage(self) -> None:
        cases = (
            (WALK, StatementStatus.POSITIVE, TravelMode.WALKING),
            (VEHICLE, StatementStatus.POSITIVE, TravelMode.VEHICLE),
            (BLOCK, StatementStatus.BLOCKED, TravelMode.UNSPECIFIED),
            ("걸어갈 수 없다.", StatementStatus.BLOCKED, TravelMode.WALKING),
            ("걸어갈 수 있다고 들었다.", StatementStatus.UNKNOWN, TravelMode.WALKING),
            ("연결되는지는 모르겠다.", StatementStatus.UNKNOWN, TravelMode.UNSPECIFIED),
            ("공사가 끝나면 걸어갈 수 있다.", StatementStatus.UNKNOWN, TravelMode.WALKING),
        )
        for quote, status, mode in cases:
            with self.subTest(quote=quote):
                assessment = assess_statement(quote)
                self.assertEqual((assessment.status, assessment.mode), (status, mode))

    def test_blocked_winner_is_replaced_by_positive_without_reordering_places(self) -> None:
        positive = document(WALK)
        blocked = document(BLOCK, conditions=("공사로 길이 막혀",))
        row = candidate(902, [blocked, positive], [0.9, 0.1])
        before = deepcopy(row)
        contexts = {902: EvidenceContext((positive, blocked), ContextCoverage.ACTIVE)}
        batch = apply_connection_quality([(row, 0.9)], self.requirement, contexts)
        accepted, score = batch.accepted[0]
        self.assertEqual(score, 0.9)
        self.assertEqual(accepted["evidence_assessment"]["representative_rerank_score"], 0.1)
        self.assertEqual(accepted["evidence_assessment"]["status"], DecisionStatus.CONFLICT)
        self.assertEqual(accepted["evidence"]["chunk_id"], positive["chunk_id"])
        self.assertEqual(accepted["reranked_evidence_chunks"][0]["chunk_id"], positive["chunk_id"])
        self.assertIn(WALK, accepted["description"])
        self.assertIn(BLOCK, accepted["description"])
        self.assertIn("확정할 수 없습니다", accepted["description"])
        self.assertEqual(row, before)
        self.assertEqual(len(accepted["reranked_evidence_chunks"]), 2)

    def test_active_block_outside_reranking_budget_is_preserved_and_dates_do_not_resolve_it(self) -> None:
        positive = document(WALK, importance="supporting")
        blocked = document(BLOCK)
        positive["metadata"] = {"published_at": "2026-10-31"}
        blocked["metadata"] = {"published_at": "2024-01-01"}
        row = candidate(901, [positive], [0.01])
        requirement = question_requirement(
            "연결된 공원",
            ObservationFilter.from_mapping({"destination_place_id": 902, "relation_importance": ["supporting"]}),
        )
        batch = apply_connection_quality(
            [(row, 0.01)],
            requirement,
            {901: EvidenceContext((positive, blocked), ContextCoverage.ACTIVE)},
        )
        accepted = batch.accepted[0][0]
        self.assertEqual(len(accepted["reranked_evidence_chunks"]), 1)
        self.assertEqual(len(accepted["evidence_assessment"]["blocking_evidence"]), 1)
        self.assertEqual(accepted["evidence_assessment"]["current_accessibility"], "unverified")

    def test_missing_connection_is_withheld_even_with_high_score_and_low_positive_score_is_kept(self) -> None:
        unrelated = document("벚꽃나무 쪽에 흙길이 보인다.", relation=False)
        positive = document(WALK)
        rows = [(candidate(901, [unrelated], [0.99]), 0.99), (candidate(902, [positive], [0.00001]), 0.00001)]
        batch = apply_connection_quality(rows, self.requirement, {})
        self.assertEqual([row["place_id"] for row, _ in batch.accepted], [902])
        self.assertEqual(batch.withheld[0]["reason"], WithholdingReason.NO_RELATION)
        self.assertEqual(batch.withheld[0]["evidence_chunks"][0]["chunk_text"], unrelated["chunk_text"])

    def test_walking_and_vehicle_places_keep_relative_order_without_walking_preference(self) -> None:
        vehicle = document(VEHICLE, origin=920, destination=930, conditions=("도보 통행은 금지된다",))
        walking = document(WALK, origin=940, destination=950)
        rows = [(candidate(920, [vehicle], [0.01]), 0.01), (candidate(940, [walking], [0.001]), 0.001)]
        batch = apply_connection_quality(rows, self.requirement, {})
        self.assertEqual([row["place_id"] for row, _ in batch.accepted], [920, 940])
        self.assertIn("도보 통행은 금지된다", batch.accepted[0][0]["description"])
        walking_requirement = question_requirement("도보로 연결된 곳", None)
        only_walking = apply_connection_quality(rows, walking_requirement, {})
        self.assertEqual([row["place_id"] for row, _ in only_walking.accepted], [940])
        self.assertEqual(only_walking.withheld[0]["reason"], WithholdingReason.MODE)

    def test_reverse_and_unrelated_edges_do_not_create_false_conflict(self) -> None:
        positive = document(WALK)
        other = [document(BLOCK, origin=902, destination=901), document(BLOCK, destination=903)]
        batch = apply_connection_quality(
            [(candidate(901, [positive], [0.2]), 0.2)],
            self.requirement,
            {901: EvidenceContext((positive, *other), ContextCoverage.ACTIVE)},
        )
        self.assertEqual(batch.accepted[0][0]["evidence_assessment"]["blocking_evidence"], [])

    def test_blocked_only_and_unknown_statements_are_withheld_with_separate_reasons(self) -> None:
        for quote, reason in ((BLOCK, WithholdingReason.NO_POSITIVE), ("도착공원으로 이어질지도 모른다.", WithholdingReason.UNASSESSED)):
            with self.subTest(quote=quote):
                row = candidate(901, [document(quote)], [0.9])
                batch = apply_connection_quality([(row, 0.9)], self.requirement, {})
                self.assertEqual(batch.accepted, [])
                self.assertEqual(batch.withheld[0]["reason"], reason)

    def test_same_place_ids_and_unspecified_mode_do_not_hide_blocking_reports(self) -> None:
        positive = document("출발공원에서 도착공원으로 연결되어 있다.")
        blocked = document("출발공원에서 도착공원까지 걸어갈 수 없다.")
        blocked["relations"][0]["origin"]["name"] = "출발공원의 다른 표기"
        blocked["relations"][0]["destination"]["name"] = "도착공원의 다른 표기"
        batch = apply_connection_quality(
            [(candidate(901, [positive], [0.2]), 0.2)],
            self.requirement,
            {901: EvidenceContext((positive, blocked), ContextCoverage.ACTIVE)},
        )
        assessment = batch.accepted[0][0]["evidence_assessment"]
        self.assertEqual(assessment["status"], DecisionStatus.CONFLICT)
        self.assertEqual(assessment["blocking_evidence"][0]["origin"], blocked["relations"][0]["origin"])

    def test_changed_snapshot_is_withheld_and_scenery_queries_are_not_filtered(self) -> None:
        positive = document(WALK)
        row = candidate(901, [positive], [0.2])
        changed = apply_connection_quality(
            [(row, 0.2)],
            self.requirement,
            {901: EvidenceContext((), ContextCoverage.CHANGED)},
        )
        self.assertEqual(changed.withheld[0]["reason"], WithholdingReason.SNAPSHOT)
        scenery = question_requirement("야경이 아름다운 공원", None)
        self.assertEqual(scenery.scope, RequirementScope.OTHER)
        self.assertEqual(apply_connection_quality([(row, 0.2)], scenery, {}).accepted, [(row, 0.2)])

    def test_tampered_quotation_is_rejected_instead_of_claiming_support(self) -> None:
        altered = document(WALK)
        altered["relations"][0]["evidence"]["quote"] = "다른 원문"
        with self.assertRaises(ValueError):
            apply_connection_quality([(candidate(901, [altered], [0.5]), 0.5)], self.requirement, {})

    def test_positive_context_does_not_silently_promote_unscored_evidence(self) -> None:
        positive = document(WALK)
        blocked = document(BLOCK)
        row = candidate(902, [blocked], [0.9])
        batch = apply_connection_quality(
            [(row, 0.9)],
            self.requirement,
            {902: EvidenceContext((positive, blocked), ContextCoverage.ACTIVE)},
        )
        self.assertEqual(batch.accepted, [])
        self.assertEqual(len(batch.withheld[0]["active_relation_context"]), 2)
        self.assertEqual(batch.withheld[0]["reason"], WithholdingReason.NO_POSITIVE)


if __name__ == "__main__":
    unittest.main()
