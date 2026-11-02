"""Original-field identity and post-retrieval attachment without model calls."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.contextual.original_fields import FrozenSnapshot, attach_original_fields, description_evidence, validate_description_evidence
from app.contextual.ranking import EvidenceCount, build_pairs, rank_places
from app.enrichment.contracts import ExistingPlace


class OriginalFieldsTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.place = ExistingPlace(place_id=311, name="Park", description="No overnight access.\n" + "original; " * 80,
                                   tour_content_id="2761797")
        self.snapshot = FrozenSnapshot("1.4.0", "a" * 64, "b" * 64, "c" * 64)
        self.document = description_evidence(self.place, self.snapshot)

    def test_full_original_and_explicit_provenance_without_fabricated_supplement(self) -> None:
        self.assertEqual(self.place.description, self.document["chunk_text"])
        self.assertGreater(len(self.document["chunk_text"]), 400)
        self.assertEqual("tourapi", self.document["source_type"])
        self.assertEqual("NOT_EMBEDDED", self.document["vector_binding"])
        self.assertEqual(311, self.document["metadata"]["place_id"])
        for absent in ("context_text", "generation", "relations", "hypothetical_questions"):
            self.assertNotIn(absent, self.document)
        for absent in ("source_url", "fetched_at", "collected_at", "published_at"):
            self.assertNotIn(absent, self.document["metadata"])
        validate_description_evidence(self.document, self.place)

    def test_content_source_kind_ownership_and_snapshot_tampering_are_rejected(self) -> None:
        for field, value in (("chunk_text", "Overnight access permitted."), ("source_type", "review")):
            changed = deepcopy(self.document)
            changed[field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_description_evidence(changed, self.place)
        changed = deepcopy(self.document)
        changed["metadata"]["place_id"] = 378
        with self.assertRaises(ValueError):
            validate_description_evidence(changed, self.place)
        other = description_evidence(self.place, FrozenSnapshot("1.4.1", "d" * 64, "e" * 64, "c" * 64))
        self.assertNotEqual(other["chunk_id"], self.document["chunk_id"])

    def test_missing_real_tourapi_id_is_not_replaced_by_place_id(self) -> None:
        with self.assertRaises(ValueError):
            description_evidence(ExistingPlace(place_id=1, name="Unknown", description="Text"), self.snapshot)

    async def test_attachment_preserves_candidate_score_and_existing_review_evidence(self) -> None:
        document, place = self.document, self.place
        class Pool:
            async def fetch(self, statement: str, identifiers: list[int]) -> list[dict]:
                return [{"place_id": place.place_id, "document": json.dumps(document),
                         "place_fingerprint": place.source_fingerprint, "current_place": json.dumps(place.to_dict())}]
        review = {"source_type": "review", "chunk_text": "Visited yesterday"}
        rows = [{"place_id": 311, "source_version": 1, "semantic_score": 0.25, "evidence": None},
                {"place_id": 378, "source_version": 1, "semantic_score": 0.99, "evidence": review}]
        attached = await attach_original_fields(Pool(), rows)
        self.assertEqual([0.25, 0.99], [row["semantic_score"] for row in attached])
        self.assertIs(review, attached[1]["evidence"])
        self.assertIsNone(rows[0]["evidence"])
        pairs = build_pairs([attached[0]], [attached[0]], EvidenceCount.TWO)
        self.assertEqual(self.place.description, pairs[0].text)
        ranked = rank_places([attached[0]], pairs, [0.5])
        self.assertEqual(self.place.description, ranked[0][0]["reranked_evidence_chunks"][0]["chunk_text"])

    async def test_stale_place_fingerprint_does_not_attach_old_original(self) -> None:
        document, place = self.document, self.place
        class Pool:
            async def fetch(self, statement: str, identifiers: list[int]) -> list[dict]:
                return [{"place_id": place.place_id, "document": document, "place_fingerprint": "outdated",
                         "current_place": place.to_dict()}]
        rows = [{"place_id": 311, "evidence": None}]
        self.assertIsNone((await attach_original_fields(Pool(), rows))[0]["evidence"])


if __name__ == "__main__":
    unittest.main()
