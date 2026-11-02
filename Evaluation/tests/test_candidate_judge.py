"""Protect evidence validity, blindness and honest authorship in AI place assessments."""
from __future__ import annotations

import copy
from pathlib import Path
import sys
from typing import Any
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tracks.search.judge_candidates import merge_assessments, payload_for, recover_source_quote, validate_judgments


class CandidateJudgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.candidate = {
            "case_id": "synthetic-case", "candidate_key": "synthetic-candidate",
            "query": "강변 산책길을 찾아줘", "conditions": "{}",
            "place_name": "테스트공원", "place_region": "서울", "place_city": "마포",
            "description": "강변 산책로와 휴식 공간이 있다.",
            "relevance": "", "evidence": "", "rationale": "",
            "review_status": "pending", "reviewer": "",
        }
        self.judgment = {
            "candidate_key": self.candidate["candidate_key"], "relevance": "3",
            "evidence_quotes": [{"field": "description", "quote": "강변 산책로와 휴식 공간"}],
            "rationale": "강변을 걸을 수 있는 산책로가 명시돼 있다.",
            "uncertainty_reason": None, "confidence": "high",
        }

    def result(self) -> dict[str, Any]:
        key = self.candidate["candidate_key"]
        return {
            "case_id": self.candidate["case_id"],
            "judgments": {key: self.judgment}, "independent": {key: self.judgment},
            "disagreed_keys": [],
        }

    def test_quoted_evidence_must_exist_in_that_candidate(self) -> None:
        valid = validate_judgments({"judgments": [self.judgment]}, [self.candidate])
        self.assertEqual(valid[self.candidate["candidate_key"]]["relevance"], "3")
        fabricated = copy.deepcopy(self.judgment)
        fabricated["evidence_quotes"][0]["quote"] = "언제나 조용하고 사람이 전혀 없다"
        with self.assertRaisesRegex(ValueError, "exact source"):
            validate_judgments({"judgments": [fabricated]}, [self.candidate])

    def test_missing_and_duplicate_candidate_judgments_are_rejected(self) -> None:
        for judgments in ([], [self.judgment, self.judgment]):
            with self.subTest(count=len(judgments)), self.assertRaisesRegex(ValueError, "exactly once"):
                validate_judgments({"judgments": judgments}, [self.candidate])

    def test_unknown_requires_a_missing_evidence_reason(self) -> None:
        unknown = {**self.judgment, "relevance": "unknown"}
        with self.assertRaisesRegex(ValueError, "unknown needs"):
            validate_judgments({"judgments": [unknown]}, [self.candidate])

    def test_payload_excludes_prior_labels_and_search_identity(self) -> None:
        populated = {**self.candidate, "relevance": "2", "ranking_mode": "secret-mode", "score": "0.9"}
        payload = payload_for([populated])
        self.assertEqual(set(payload), {"query", "conditions", "candidates"})
        self.assertFalse({"relevance", "ranking_mode", "score", "reviewer"} & payload["candidates"][0].keys())

    def test_ai_completion_does_not_claim_human_review(self) -> None:
        merged = merge_assessments([self.candidate], [self.result()], "synthetic-model")
        self.assertEqual(merged[0]["review_status"], "completed")
        self.assertEqual(merged[0]["human_review_status"], "pending")
        self.assertEqual(merged[0]["label_source"], "ai_judgment")
        self.assertEqual(merged[0]["reviewer"], "AI:synthetic-model")

    def test_existing_user_judgments_are_preserved(self) -> None:
        completed = {**self.candidate, "relevance": "1", "reviewer": "human-reviewer", "rationale": "사용자가 직접 입력"}
        merged = merge_assessments([completed], [], "synthetic-model")
        for name, value in completed.items():
            self.assertEqual(merged[0][name], value)

    def test_only_formatting_can_be_restored_from_the_actual_source(self) -> None:
        source = "강변 산책로가 있다.\\n반려견 출입은 불가하다."
        self.assertEqual(recover_source_quote("강변산책로가 있다.", source), "강변 산책로가 있다.")
        self.assertEqual(recover_source_quote("강변 산책로가 있다.\n반려견 출입은 불가하다.", source), source)
        opposite = "반려견 출입은 가능하다."
        self.assertEqual(recover_source_quote(opposite, source), opposite)
        self.assertNotIn(recover_source_quote(opposite, source), source)


if __name__ == "__main__":
    unittest.main()
