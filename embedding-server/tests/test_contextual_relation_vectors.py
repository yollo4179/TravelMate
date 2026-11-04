"""이동 인용 벡터의 입력·저장·후보 SQL·원문 리랭킹 경계를 검사한다."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import time
from typing import Any
import unittest
from unittest.mock import AsyncMock, MagicMock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]
from app.contextual.contracts import ContentKind
from app.contextual.observation_search import ObservationFilter
from app.contextual.relation_vectors import RelationRetrievalMode, relation_embedding_inputs, relation_vector_sql
from app.contextual.repository import store_relation_embeddings
from app.contextual.ranking import EvidenceCount, build_pairs
from app.contextual.retrieval import resolve_retrieval_strategy
from test_contextual_supporting_relations import fixture, parsed, QUOTE, TEXT
from test_contextual_subject_filter import mock_database


class RelationVectorTests(unittest.IsolatedAsyncioTestCase):
    def test_index_text_is_exact_quote_without_scenery_or_generated_questions(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        entry, = relation_embedding_inputs([chunk])
        self.assertEqual(entry.text, QUOTE)
        self.assertNotIn("야경", entry.text)
        self.assertEqual(entry.relation_index, 0)
        entry.evidence["start"] = 0
        self.assertEqual(chunk.relations[0]["evidence"]["start"], 15)
        self.assertEqual(relation_embedding_inputs([]), [])
        self.assertEqual(RelationRetrievalMode("chunk-only"), RelationRetrievalMode.CHUNK_ONLY)
        with self.assertRaises(ValueError):
            RelationRetrievalMode("automatic")

    def test_legacy_unquoted_relation_is_not_given_invented_evidence(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        legacy = deepcopy(chunk)
        object.__setattr__(legacy, "content_kind", ContentKind.MOVEMENT)
        object.__setattr__(legacy, "relations", [{key: value for key, value in chunk.relations[0].items()
                                                if key not in ("type", "importance", "evidence")}])
        self.assertEqual(relation_embedding_inputs([legacy]), [])

    def test_relation_sql_uses_exact_edge_direction_importance_and_context(self) -> None:
        condition = ObservationFilter.from_mapping({"destination_place_id": 395, "relation_importance": ["supporting"]})
        parameters = ["vector"]
        join, extension = relation_vector_sql(condition, parameters)
        self.assertIn("e.context_version=c.context_version", join)
        self.assertIn("->e.relation_index", join)
        self.assertIn("->'destination'->>'place_id'", join)
        self.assertIn("->>'importance'", join)
        self.assertIn("p.place_id", join)
        self.assertIn("UNION ALL", join)
        self.assertIn("LIMIT 1", join)
        self.assertNotIn("SUM(", join)
        self.assertIn("retrieved_relation_index", extension)
        self.assertEqual(json.loads(parameters[1])["destination_place_id"], 395)

    def test_relation_hit_is_reranked_using_only_its_actual_quote(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        evidence = {**chunk.to_dict(), "context_version": chunk.context_version, "retrieved_relation_index": 0, "retrieval_path": "relation"}
        condition = ObservationFilter.from_mapping({"content_kinds": ["landscape", "movement"]})
        document = condition.scope_evidence(394, evidence)
        self.assertEqual(document["matched_relations"], chunk.relations)
        self.assertNotIn("야경", document["search_text"])
        self.assertEqual(document["chunk_text"], TEXT)
        pairs = build_pairs([{"place_id": 394, "source_version": 1, "semantic_score": 0.8, "evidence": document}], [], EvidenceCount.ONE)
        self.assertIn(QUOTE, pairs[0].text)
        self.assertNotIn("야경", pairs[0].text)

    def test_mismatched_or_invalid_relation_index_is_rejected(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        condition = ObservationFilter.from_mapping({"origin_place_id": 394})
        for index in (-1, 1, True, "0"):
            with self.subTest(index=index), self.assertRaises(ValueError):
                condition.scope_evidence(395, {**chunk.to_dict(), "retrieved_relation_index": index})
        with self.assertRaises(ValueError):
            condition.scope_evidence(394, {**chunk.to_dict(), "retrieved_relation_index": 0})

    async def test_invalid_vector_count_dimension_and_values_write_nothing(self) -> None:
        bundle, raw = fixture()
        inputs = relation_embedding_inputs(parsed(bundle, raw))
        for vectors in ([], [[0.0]], [[float("nan")] * 1024], [[float("inf")] * 1024]):
            connection = AsyncMock()
            with self.assertRaises(ValueError):
                await store_relation_embeddings(connection, inputs, vectors)
            connection.execute.assert_not_called()
        connection = AsyncMock()
        await store_relation_embeddings(connection, inputs, [[1.0] + [0.0] * 1023])
        self.assertIn("retrieval_relation_embeddings", connection.execute.await_args.args[0])
        self.assertEqual(json.loads(connection.execute.await_args.args[5])["quote"], QUOTE)

    async def test_default_and_observation_only_paths_do_not_query_relation_vectors(self) -> None:
        module = ast.parse((ROOT / "app/kafka_runtime.py").read_text(encoding="utf-8"))
        runtime = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
        methods = [node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef) and node.name in ("_retrieve_candidates", "_retrieve_evidence")]
        trace = MagicMock()
        namespace = {"PlaceMetadataFilter": __import__("app.contextual.metadata_filter", fromlist=["PlaceMetadataFilter"]).PlaceMetadataFilter, "Any": Any, "ObservationFilter": ObservationFilter, "EvidenceCount": EvidenceCount,
                     "resolve_retrieval_strategy": resolve_retrieval_strategy,
                     "time": time, "tracer": lambda: trace, "RETRIEVE_TOP_K": 30}
        exec(compile(ast.Module(body=methods, type_ignores=[]), "<relation-search>", "exec"), namespace)
        pool, connection = mock_database({})
        connection.fetch.return_value = []
        target = MagicMock(database_pool=pool, use_relation_vectors=False)
        target._attach_original_fields = AsyncMock(side_effect=lambda rows, _: rows)
        move = {"origin_place_id": 394}
        await namespace["_retrieve_candidates"](target, {"filters": {"observation": move}}, "[0]")
        self.assertNotIn("retrieval_relation_embeddings", connection.fetch.await_args.args[0])
        target.use_relation_vectors = True
        await namespace["_retrieve_candidates"](target, {"filters": {"observation": {"content_kinds": ["landscape"]}}}, "[0]")
        self.assertNotIn("retrieval_relation_embeddings", connection.fetch.await_args.args[0])
        await namespace["_retrieve_candidates"](target, {"filters": {"observation": move}}, "[0]")
        self.assertIn("retrieval_relation_embeddings", connection.fetch.await_args.args[0])
        self.assertEqual(connection.fetch.await_args.args[-1], 30)

    def test_schema_copies_match_and_keep_twenty_slot_constraint(self) -> None:
        primary = (ROOT / "app/contextual/schema.sql").read_text(encoding="utf-8")
        replica = (ROOT.parent / "Docker/search-init/03-contextual-chunks.sql").read_text(encoding="utf-8")
        self.assertEqual(primary, replica)
        self.assertIn("slot BETWEEN 1 AND 20", primary)
        self.assertIn("selected.relation->'evidence'=NEW.evidence", primary)
        self.assertIn("substring(r.chunk_text", primary)


if __name__ == "__main__":
    unittest.main()
