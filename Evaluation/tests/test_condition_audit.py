"""A partially supported conjunction must never become a relevant match."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from tracks.search.audit_candidate_conditions import ConditionSupport, audit_grade, referenced_payload, resolve_references


class ConditionAuditTests(unittest.TestCase):
    def test_missing_essential_condition_is_unknown(self) -> None:
        assessment = {
            "clearly_irrelevant": False,
            "conditions": [{"support": ConditionSupport.SUPPORTED}, {"support": ConditionSupport.UNKNOWN}],
        }
        self.assertEqual(audit_grade(assessment), "unknown")

    def test_explicit_violation_is_partial_and_unrelated_place_is_zero(self) -> None:
        assessment = {"clearly_irrelevant": False, "conditions": [{"support": ConditionSupport.VIOLATED}]}
        self.assertEqual(audit_grade(assessment), "1")
        assessment["clearly_irrelevant"] = True
        self.assertEqual(audit_grade(assessment), "0")

    def test_all_required_conditions_need_support_for_full_relevance(self) -> None:
        assessment = {"clearly_irrelevant": False, "conditions": [{"support": ConditionSupport.SUPPORTED}]}
        self.assertEqual(audit_grade(assessment), "3")

    def test_source_spans_preserve_the_entire_description(self) -> None:
        description = "가나다 " * 120
        candidate = {"candidate_key": "C01", "query": "산책", "conditions": "{}", "place_name": "공원", "place_region": "서울", "place_city": "중", "description": description}
        payload, references = referenced_payload([candidate])
        spans = payload["candidates"][0]["source_spans"]
        self.assertEqual("".join(span["text"] for span in spans if span["field"] == "description"), description)
        identifier = next(span["id"] for span in spans if span["field"] == "description")
        resolved = resolve_references({"judgments": [{"candidate_key": "C01", "conditions": [{"evidence_id": identifier}]}]}, references)
        self.assertIn(resolved["judgments"][0]["conditions"][0]["quote"], description)

    def test_a_reference_cannot_borrow_another_candidates_evidence(self) -> None:
        references = {"C02:description:0": {"candidate_key": "C02", "field": "description", "text": "숲길이 있다"}}
        document = {"judgments": [{"candidate_key": "C01", "conditions": [{"evidence_id": "C02:description:0"}]}]}
        with self.assertRaises(ValueError):
            resolve_references(document, references)
