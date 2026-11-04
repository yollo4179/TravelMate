"""혼합 관찰의 보조 관계를 보존하고 주체 귀속과 분리해 검색하는 회귀 검사."""
from __future__ import annotations

import ast
from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import time
from typing import Any
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.contextual.agent import SCHEMA_V6, parse_chunks, schema_for_prompt
from app.contextual.artifacts import SourceBundle, collect_bundle, load_record, revalidate_record
from app.contextual.contracts import SearchChunk, SplitterVersion
from app.contextual.input_format import InputVersion
from app.contextual.observation_search import ObservationFilter
from app.contextual.pipeline import select_active, split_source, index_embedding_inputs
from app.contextual.prompts import PromptVersion, resolve_prompt
from app.contextual.ranking import EvidenceCount, build_pairs
from app.contextual.relations import ActiveChunkRole
from app.contextual.repository import activate_chunks, apply_bundle
from app.contextual.review import approval_document, reviewed_chunks, selection_report
from app.contextual.validation import ValidationVersion
from app.enrichment.contracts import ExistingPlace
from test_contextual_chunks import SETTINGS
from test_contextual_subject_filter import mock_database

A = ExistingPlace(394, "A공원")
B = ExistingPlace(395, "B공원")
TEXT = "A공원은 야경이 아름답고, 관람 후 B공원으로 걸어갈 수 있다."
QUOTE = "관람 후 B공원으로 걸어갈 수 있다."


def fixture() -> tuple[SourceBundle, dict[str, Any]]:
    bundle = SourceBundle.from_mapping({"places": [A.to_dict(), B.to_dict()], "sources": [{
        "source_type": "review", "title": "관찰과 이동", "text": TEXT,
        "metadata": {"source_url": "https://example.org/supporting-route", "capture_scope": "full_text"}}]})
    source = bundle.sources[0]
    row = {"source_id": source.source_id, "start": 0, "end": len(TEXT),
        "context_text": "A공원의 야경 관찰과 관람 후 B공원으로 걸어서 이동할 수 있다는 내용이다.",
        "content_kind": "landscape", "place_refs": [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "mentioned"}],
        "entities": [], "hypothetical_questions": [], "relations": [{
            "type": "movement", "importance": "supporting", "origin": {"place_id": 394, "name": "A공원"},
            "destination": {"place_id": 395, "name": "B공원"}, "conditions": [],
            "evidence": {"start": TEXT.index(QUOTE), "end": len(TEXT), "quote": QUOTE}}]}
    raw = {"id": "supporting-mock-only", "model": "mock", "status": "completed", "output": [{
        "type": "message", "content": [{"type": "output_text", "text": json.dumps({"chunks": [row]}, ensure_ascii=False)}]}]}
    return bundle, raw


def rows(raw: dict[str, Any]) -> dict[str, Any]:
    return json.loads(raw["output"][0]["content"][0]["text"])


def changed(raw: dict[str, Any], document: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(raw)
    result["output"][0]["content"][0]["text"] = json.dumps(document, ensure_ascii=False)
    return result


def parsed(bundle: SourceBundle, raw: dict[str, Any]) -> list[SearchChunk]:
    return parse_chunks(raw, bundle.places, bundle.sources, prompt_version=PromptVersion.V7,
                        splitter_version=SplitterVersion.SENTENCE, validation_version=ValidationVersion.RELATIONS)


class SupportingRelationTests(unittest.IsolatedAsyncioTestCase):
    def test_one_chunk_keeps_a_as_landscape_subject_and_b_as_mentioned(self) -> None:
        bundle, raw = fixture()
        self.assertEqual(split_source(bundle.sources[0], splitter_version=SplitterVersion.SENTENCE), [(0, len(TEXT))])
        chunk, = parsed(bundle, raw)
        self.assertEqual(chunk.chunk_text, TEXT)
        self.assertEqual(chunk.subject_place_ids, {394})
        self.assertEqual(chunk.relation_place_ids, {394, 395})
        self.assertEqual(chunk.active_role(394), ActiveChunkRole.SUBJECT)
        self.assertEqual(chunk.active_role(395), ActiveChunkRole.RELATION_ENDPOINT)
        self.assertEqual(chunk.place_refs[1]["role"], "mentioned")
        self.assertEqual(SearchChunk.from_mapping(chunk.source, chunk.to_dict()), chunk)
        self.assertEqual(select_active(395, [chunk]), [chunk])
        scenery = ObservationFilter.from_mapping({"content_kinds": ["landscape"]})
        self.assertTrue(scenery.matches(394, chunk.to_dict()))
        self.assertFalse(scenery.matches(395, chunk.to_dict()))
        self.assertEqual(ObservationFilter.from_mapping(scenery.to_dict()), scenery)

    def test_both_directions_and_both_importance_values_are_searchable(self) -> None:
        bundle, raw = fixture()
        for importance in ("primary", "supporting"):
            document = rows(raw)
            document["chunks"][0]["relations"][0]["importance"] = importance
            chunk, = parsed(bundle, changed(raw, document))
            to_b = ObservationFilter.from_mapping({"destination_place_id": 395, "relation_importance": [importance]})
            from_a = ObservationFilter.from_mapping({"origin_place_id": 394})
            self.assertTrue(to_b.matches(394, chunk.to_dict()))
            self.assertFalse(to_b.matches(395, chunk.to_dict()))
            self.assertTrue(from_a.matches(395, chunk.to_dict()))
            other = "primary" if importance == "supporting" else "supporting"
            self.assertFalse(ObservationFilter.from_mapping({"relation_importance": [other]}).matches(394, chunk.to_dict()))
        for kind in ("facility", "other", "movement"):
            document = rows(raw)
            document["chunks"][0]["content_kind"] = kind
            self.assertEqual(len(parsed(bundle, changed(raw, document))), 1)

    def test_relation_only_participants_are_searchable_without_inventing_subject(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["place_refs"][0]["role"] = "mentioned"
        chunk, = parsed(bundle, changed(raw, document))
        self.assertEqual(chunk.subject_place_ids, set())
        self.assertEqual(chunk.active_role(394), ActiveChunkRole.RELATION_ENDPOINT)
        self.assertFalse(ObservationFilter.from_mapping({"content_kinds": ["landscape"]}).matches(394, chunk.to_dict()))
        self.assertTrue(ObservationFilter.from_mapping({"origin_place_id": 394}).matches(395, chunk.to_dict()))

    def test_route_reranking_uses_exact_route_evidence_without_a_scenery(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        evidence = {**chunk.to_dict(), "context_version": chunk.context_version}
        condition = ObservationFilter.from_mapping({"origin_place_id": 394})
        candidate, = condition.scope_rows([{"place_id": 395, "source_version": "v", "semantic_score": 0.8, "evidence": json.dumps(evidence)}])
        self.assertNotIn("야경", candidate["description"])
        self.assertIn(QUOTE, candidate["description"])
        self.assertIn("출발지: A공원", candidate["description"])
        self.assertIn("도착지: B공원", candidate["description"])
        self.assertEqual(candidate["evidence"]["chunk_text"], TEXT)
        self.assertEqual(candidate["evidence"]["place_refs"][1]["role"], "mentioned")
        for count in EvidenceCount:
            pairs = build_pairs([candidate], [candidate] if count != EvidenceCount.ONE else [], count)
            self.assertNotIn("야경", pairs[0].text)
            self.assertIn(QUOTE, pairs[0].text)
        self.assertNotIn("search_text", evidence)
        mixed = ObservationFilter.from_mapping({"content_kinds": ["landscape", "movement"]})
        self.assertTrue(mixed.matches(394, evidence))
        self.assertTrue(mixed.matches(395, evidence))
        self.assertNotIn("야경", mixed.scope_evidence(395, evidence)["search_text"])

    def test_bad_evidence_unknown_ids_and_conditions_from_another_clause_are_quarantined(self) -> None:
        bundle, raw = fixture()
        for mutation in ("outside", "changed_quote", "unknown_id", "wrong_name", "missing_reference", "condition"):
            with self.subTest(mutation=mutation):
                document = rows(raw)
                row = document["chunks"][0]
                relation = row["relations"][0]
                if mutation == "outside": relation["evidence"]["end"] += 1
                if mutation == "changed_quote": relation["evidence"]["quote"] = "쉽고 평탄하다"
                if mutation == "unknown_id": relation["destination"]["place_id"] = 999
                if mutation == "wrong_name": relation["destination"]["name"] = "C공원"
                if mutation == "missing_reference": row["place_refs"] = row["place_refs"][:1]
                if mutation == "condition": relation["conditions"] = [{"kind": "other", "quote": "야경이 아름답고"}]
                self.assertEqual(parsed(bundle, changed(raw, document)), [])
        for mutation in ("missing", "invalid"):
            document = rows(raw)
            relation = document["chunks"][0]["relations"][0]
            if mutation == "missing": del relation["importance"]
            else: relation["importance"] = "secondary"
            with self.assertRaises(ValidationError):
                parsed(bundle, changed(raw, document))

    async def test_activation_keeps_subject_and_relation_endpoint_roles_separate(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        for place_id, role in ((394, "subject"), (395, "relation_endpoint")):
            connection = AsyncMock()
            await activate_chunks(connection, place_id, [chunk], [[0.0] * 1024])
            insert = next(call for call in connection.execute.await_args_list if "INSERT INTO place_active_chunks(" in call.args[0])
            self.assertEqual(insert.args[-1], role)
            self.assertEqual(chunk.place_refs[1]["role"], "mentioned")
        connection = AsyncMock()
        with self.assertRaises(ValueError):
            await activate_chunks(connection, 999, [chunk], [[0.0] * 1024])
        connection.execute.assert_not_called()

    async def test_archive_review_selection_apply_mock_and_free_revalidation(self) -> None:
        bundle, raw = fixture()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                path = await collect_bundle(bundle, SETTINGS, root / "records", client,
                    prompt_version=PromptVersion.V7, input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
            _, chunks, record = load_record(path)
            self.assertEqual(record["validation_version"], "contextual-validation-v4")
            originals = {name: path.with_name(name).read_bytes() for name in ("record.json", "request.json", "sources.json", "raw_response.json")}
            with patch('httpx.AsyncClient', side_effect=AssertionError("재검증 HTTP 금지")):
                replay = revalidate_record(path, root / "replay")
            self.assertEqual(load_record(replay)[1][0].to_dict(), chunks[0].to_dict())
            approval = root / "approval.json"
            approval.write_text(json.dumps(approval_document(path, [chunks[0].chunk_id], "합성 검수")), encoding='utf-8')
            self.assertEqual(len(reviewed_chunks(path, approval)), 1)
            report = selection_report(path, approval)
            self.assertEqual([len(row["selected_chunk_ids"]) for row in report["places"]], [1, 1])
            pool, connection = mock_database({394: {**A.to_dict(), "document_status": "READY", "source_version": 1, "latest_seen_version": 1},
                                              395: {**B.to_dict(), "document_status": "READY", "source_version": 1, "latest_seen_version": 1}})
            self.assertEqual(await apply_bundle(pool, path, review_path=approval), "REINDEX_QUEUED")
            self.assertEqual([call.args[1] for call in connection.fetchrow.await_args_list], [394, 395])
            self.assertEqual(originals, {name: path.with_name(name).read_bytes() for name in originals})

    def test_destination_fallback_vector_never_uses_origin_scenery(self) -> None:
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        for place in (A, B):
            texts, primary = index_embedding_inputs(place, [chunk])
            self.assertEqual(texts[0], chunk.embedding_text)
            if place == A:
                self.assertEqual(primary, 0)
            else:
                self.assertNotIn("야경", texts[primary])
                self.assertEqual(len(texts), 2)
        self.assertEqual(index_embedding_inputs(B, []), (["B공원."], 0))

    def test_v6_schema_stays_frozen_and_v7_requires_new_relation_fields(self) -> None:
        self.assertEqual(schema_for_prompt(PromptVersion.V6), SCHEMA_V6)
        schema = schema_for_prompt(PromptVersion.V6)
        self.assertNotIn("importance", schema["properties"]["chunks"]["items"]["properties"]["relations"]["items"]["properties"])
        self.assertNotEqual(schema_for_prompt(PromptVersion.V7), schema)
        self.assertFalse(resolve_prompt(PromptVersion.V6).independent_relations)
        self.assertIn("supporting", resolve_prompt(PromptVersion.V7).instructions)

    async def test_runtime_queries_keep_relation_roles_and_scoped_input_in_both_search_stages(self) -> None:
        # 실제 메서드를 추출해 SQL 생성과 반환 범위를 확인한다. DB·모델은 호출하지 않는다.
        module = ast.parse((ROOT / "app/kafka_runtime.py").read_text(encoding='utf-8'))
        runtime = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
        methods = [node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef) and node.name in ("_retrieve_candidates", "_retrieve_evidence")]
        trace = MagicMock()
        from app.contextual.retrieval import resolve_retrieval_strategy
        namespace = {"PlaceMetadataFilter": __import__("app.contextual.metadata_filter", fromlist=["PlaceMetadataFilter"]).PlaceMetadataFilter, "Any": Any, "ObservationFilter": ObservationFilter, "EvidenceCount": EvidenceCount,
                     "resolve_retrieval_strategy": resolve_retrieval_strategy,
                     "time": time, "tracer": lambda: trace, "RETRIEVE_TOP_K": 30}
        exec(compile(ast.Module(body=methods, type_ignores=[]), '<runtime-search>', 'exec'), namespace)
        bundle, raw = fixture()
        chunk, = parsed(bundle, raw)
        pool, connection = mock_database({})
        target = MagicMock(database_pool=pool)
        target._attach_original_fields = AsyncMock(side_effect=lambda rows, _: rows)
        connection.fetch.return_value = [{"place_id": 395, "source_version": 1, "semantic_score": 0.7,
            "evidence": {**chunk.to_dict(), "context_version": chunk.context_version}}]
        condition = ObservationFilter.from_mapping({"origin_place_id": 394, "relation_importance": ["supporting"]})
        candidates = await namespace['_retrieve_candidates'](target, {"filters": {"observation": condition.to_dict()}}, "[0]")
        evidence = await namespace['_retrieve_evidence'](target, candidates, "[0]", EvidenceCount.TWO, observation=condition)
        for output in (candidates, evidence):
            self.assertNotIn("야경", output[0]["description"])
            self.assertEqual(output[0]["evidence"]["retrieval_scope"], "relation")
        for call in connection.fetch.await_args_list:
            self.assertIn("a.role IN ('subject','relation_endpoint')", call.args[0])
            self.assertIn("relation->>'importance'", call.args[0])
            self.assertIn("evidence IS NOT NULL", call.args[0])
        connection.fetch.return_value = []
        await namespace['_retrieve_candidates'](target, {"filters": {}}, "[0]")
        self.assertNotIn("relation_endpoint", connection.fetch.await_args_list[-1].args[0])


if __name__ == '__main__':
    unittest.main()
