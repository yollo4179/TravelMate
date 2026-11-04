"""Integrity and review-boundary tests; synthetic rankings are never benchmark evidence."""
from __future__ import annotations

import copy
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import read_json, read_jsonl, write_jsonl
from tracks.search.collect_holdout import check_question_review
from tracks.search.finalize_holdout import reviewed_questions
from tracks.search.holdout import (
    DEFAULT_HOLDOUT, RankingMode, check_frozen, export_requests, overlap_report,
    prepare_review, read_cases, validate_records,
)


class SearchHoldoutTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_cases(DEFAULT_HOLDOUT)
        protocol = read_json(DEFAULT_HOLDOUT / "protocol.json")
        cls.corpus = read_json(DEFAULT_HOLDOUT / protocol["corpus_path"])
        cls.corpus_ids = {place["id"] for place in cls.corpus}

    def response_rows(self, mode: RankingMode) -> list[dict]:
        identifiers = sorted(self.corpus_ids)[:3]
        ordered = identifiers if mode == RankingMode.SEMANTIC_ONLY else list(reversed(identifiers))
        return [{
            "case_id": case["case_id"], "input_sha256": case["input_sha256"],
            "ranking_mode": mode.value, "http_status": 200, "condition_coverage": "complete",
            "ranked_place_ids": ordered,
        } for case in self.cases]

    def test_frozen_set_has_no_historical_exact_overlap_or_fake_judgments(self) -> None:
        report = check_frozen(DEFAULT_HOLDOUT)
        self.assertEqual(len(self.cases), sum(report["counts_by_stratum"].values()))
        self.assertFalse(report["human_judgments_complete"])
        self.assertFalse(report["overlap"]["exact_match_case_ids"])
        self.assertLess(report["primary_family_count"], report["counts_by_stratum"]["primary"])
        for case in self.cases:
            self.assertNotIn("place_judgments", case)
            self.assertNotIn("candidate_place_ids", case["input"])

    def test_changed_manifest_is_rejected(self) -> None:
        altered = copy.deepcopy(read_json(DEFAULT_HOLDOUT / "manifest.json"))
        altered["case_count"] += 1
        with patch("tracks.search.holdout.read_json", wraps=read_json) as reader:
            reader.side_effect = lambda path: altered if path.name == "manifest.json" else read_json(path)
            with self.assertRaisesRegex(ValueError, "changed"):
                check_frozen(DEFAULT_HOLDOUT)

    def test_normalized_historical_overlap_is_detected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            history = Path(directory) / "history.jsonl"
            write_jsonl(history, [{"input": {"query": "ＳＥＯＵＬ 공원!"}}])
            report = overlap_report([{"case_id": "new", "input": {"query": "seoul공원"}}], [history])
            self.assertEqual(report["exact_match_case_ids"], ["new"])

    def test_export_contains_only_request_inputs_and_pending_review(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export"
            export_requests(DEFAULT_HOLDOUT, output)
            for row in read_jsonl(output / "inputs.jsonl"):
                self.assertEqual(set(row), {"case_id", "input", "input_sha256"})
                self.assertEqual(set(row["input"]), {"query", "conditions"})
            with self.assertRaisesRegex(ValueError, "accepted"):
                check_question_review(output / "question_review.csv", self.cases)
            with self.assertRaises(FileExistsError):
                export_requests(DEFAULT_HOLDOUT, output)

    def test_invalid_or_incomplete_rankings_cannot_be_pooled(self) -> None:
        identifiers = sorted(self.corpus_ids)
        mutations = {
            "hash": lambda rows: rows[0].update(input_sha256="wrong"),
            "failed": lambda rows: rows[0].update(http_status=500),
            "partial": lambda rows: rows[0].update(condition_coverage="partial"),
            "unknown_place": lambda rows: rows[0].update(ranked_place_ids=[max(identifiers) + 1]),
            "duplicate_place": lambda rows: rows[0].update(ranked_place_ids=[identifiers[0]] * 2),
            "missing_case": lambda rows: rows.pop(),
            "wrong_mode": lambda rows: rows[0].update(ranking_mode=RankingMode.RERANKED),
        }
        with tempfile.TemporaryDirectory() as directory:
            records_path = Path(directory) / "records.jsonl"
            for name, mutate in mutations.items():
                with self.subTest(name=name):
                    rows = self.response_rows(RankingMode.SEMANTIC_ONLY)
                    mutate(rows)
                    write_jsonl(records_path, rows)
                    with self.assertRaises(ValueError):
                        validate_records(records_path, self.cases, RankingMode.SEMANTIC_ONLY, self.corpus_ids)

    def test_human_review_must_cover_unchanged_query_and_conditions(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "export"
            export_requests(DEFAULT_HOLDOUT, output)
            review_path = output / "question_review.csv"
            with review_path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                rows = list(reader)
            for row in rows:
                row.update(decision="accept", reviewer="synthetic-reviewer")
            def save_reviews() -> None:
                with review_path.open("w", encoding="utf-8-sig", newline="") as destination:
                    writer = csv.DictWriter(destination, fieldnames=fields)
                    writer.writeheader()
                    writer.writerows(rows)
            save_reviews()
            check_question_review(review_path, self.cases)
            rows[0]["conditions"] = "{}"
            save_reviews()
            with self.assertRaisesRegex(ValueError, "conditions"):
                check_question_review(review_path, self.cases)

    def test_review_is_blind_unlabeled_and_deduplicated_with_private_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            embedding = workspace / "embedding.jsonl"
            reranking = workspace / "reranking.jsonl"
            write_jsonl(embedding, self.response_rows(RankingMode.SEMANTIC_ONLY))
            write_jsonl(reranking, self.response_rows(RankingMode.RERANKED))
            output = workspace / "review"
            prepare_review(DEFAULT_HOLDOUT, embedding, reranking, output)
            with (output / "candidates.csv").open(encoding="utf-8-sig", newline="") as source:
                reviewed = list(csv.DictReader(source))
            mapping = read_jsonl(output / "private_mapping.jsonl")
            expected_count = sum(len(set(row["ranked_place_ids"])) for row in self.response_rows(RankingMode.SEMANTIC_ONLY))
            self.assertEqual(len(reviewed), expected_count)
            self.assertEqual(len({row["candidate_key"] for row in mapping}), len(mapping))
            for row in reviewed:
                self.assertEqual(row["relevance"], "")
                self.assertEqual(row["review_status"], "pending")
                self.assertFalse({"ranking_mode", "rank", "score", "place_id"} & row.keys())
            self.assertEqual(read_json(output / "review_manifest.json")["status"], "pending_human_review")

    def test_review_finalization_requires_explicit_decisions_and_preserves_denials(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "review"
            export_requests(DEFAULT_HOLDOUT, output)
            review_path = output / "question_review.csv"
            with self.assertRaisesRegex(ValueError, "still missing"):
                reviewed_questions(DEFAULT_HOLDOUT, review_path)
            with review_path.open(encoding="utf-8-sig", newline="") as source:
                reader = csv.DictReader(source)
                fields = reader.fieldnames
                rows = list(reader)
            for row in rows:
                row.update(decision="accept", reviewer="synthetic-reviewer")
            rows[-1].update(decision="deny", notes="Outside the intended evaluation scope")
            with review_path.open("w", encoding="utf-8-sig", newline="") as destination:
                writer = csv.DictWriter(destination, fieldnames=fields)
                writer.writeheader()
                writer.writerows(rows)
            validated = reviewed_questions(DEFAULT_HOLDOUT, review_path)
            self.assertEqual(validated[-1]["decision"], "deny")
            self.assertEqual(validated[-1]["notes"], rows[-1]["notes"])


if __name__ == "__main__":
    unittest.main()
