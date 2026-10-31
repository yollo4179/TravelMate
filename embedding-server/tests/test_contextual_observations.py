"""관찰 경계·이동 관계·검수 적용·선택 상한의 회귀를 검사한다."""
from __future__ import annotations

import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, AsyncMock

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.contextual.agent import parse_chunks
from app.contextual.artifacts import SourceBundle, collect_bundle, load_record, revalidate_record
from app.contextual.contracts import ContentKind, SearchChunk, SplitterVersion
from app.contextual.input_format import InputVersion
from app.contextual.pipeline import normalize_source, select_active, split_source
from app.contextual.prompts import PromptVersion
from app.contextual.repository import apply_bundle, preserve_chunks
from app.contextual.review import approval_document, reviewed_chunks, selection_report
from app.contextual.observation_search import ObservationFilter
from app.enrichment.contracts import ExistingPlace
from test_contextual_chunks import SETTINGS


A = ExistingPlace(394, "A공원")
B = ExistingPlace(395, "B공원")
TEXT = "A공원에서 한강 전망을 감상했다.\r\nA공원에서 계단을 내려가 B공원으로 이동했다.\r\nB공원의 주차장을 이용했다.😀"


def observation_bundle() -> SourceBundle:
    return SourceBundle.from_mapping({"places": [A.to_dict(), B.to_dict()], "sources": [{
        "source_type": "review", "title": "A와 B 방문기", "text": TEXT,
        "metadata": {"source_url": "https://example.org/route", "capture_scope": "full_text"}}]})


def observation_response(value: SourceBundle) -> dict:
    item = value.sources[0]
    pieces = split_source(item, splitter_version=SplitterVersion.SENTENCE)
    rows = []
    for index, (start, end) in enumerate(pieces):
        ids = ([394], [394, 395], [395])[index]
        rows.append({"source_id": item.source_id, "start": start, "end": end,
            "context_text": ("A공원에서 감상한 한강 전망이다.", "계단을 이용한 A공원에서 B공원으로의 이동이다.", "B공원의 주차장 이용 기록이다.")[index],
            "place_refs": [{"place_id": identifier, "role": "subject"} for identifier in ids],
            "entities": [{"place_id": identifier, "name": "A공원" if identifier == 394 else "B공원", "role": "subject"} for identifier in ids],
            "hypothetical_questions": [], "content_kind": ("landscape", "movement", "facility")[index],
            "relations": [{"origin": {"place_id": 394, "name": "A공원"},
                "destination": {"place_id": 395, "name": "B공원"},
                "conditions": [{"kind": "stairs", "quote": "계단"}]}] if index == 1 else []})
    return {"id": "observations-mock", "model": "mock-sonar", "status": "completed", "output": [{
        "type": "message", "content": [{"type": "output_text", "text": json.dumps({"chunks": rows}, ensure_ascii=False)}]}]}


def parsed(raw: dict, value: SourceBundle) -> list[SearchChunk]:
    return parse_chunks(raw, value.places, value.sources, prompt_version=PromptVersion.V6,
        validation_version="contextual-validation-v2", splitter_version=SplitterVersion.SENTENCE)


class ObservationTests(unittest.IsolatedAsyncioTestCase):
    def test_direction_and_kind_filters_do_not_treat_routes_as_scenery_or_parking(self) -> None:
        value = observation_bundle()
        scene, route, parking = parsed(observation_response(value), value)
        to_b = ObservationFilter.from_mapping({"destination_place_id": 395})
        self.assertTrue(to_b.matches(394, route.to_dict()))
        self.assertFalse(to_b.matches(395, route.to_dict()))
        from_a = ObservationFilter.from_mapping({"origin_place_id": 394})
        self.assertTrue(from_a.matches(395, route.to_dict()))
        self.assertFalse(from_a.matches(394, route.to_dict()))
        scenery = ObservationFilter.from_mapping({"content_kinds": ["landscape"]})
        facilities = ObservationFilter.from_mapping({"content_kinds": ["facility"]})
        self.assertTrue(scenery.matches(394, scene.to_dict()))
        self.assertFalse(scenery.matches(394, route.to_dict()))
        self.assertTrue(facilities.matches(395, parking.to_dict()))
        self.assertFalse(facilities.matches(395, route.to_dict()))
        parameters = ["vector"]
        sql = to_b.sql_predicate(parameters)
        self.assertIn("relation->'origin'->>'place_id'", sql)
        self.assertIn("$2::jsonb", sql)
        self.assertEqual(json.loads(parameters[1])["destination_place_id"], 395)
        # 다른 관계의 subject가 조건에 맞는 관계의 참가자로 섞이면 안 된다.
        multiple = route.to_dict()
        multiple["relations"] = [
            {"origin": {"place_id": 396}, "destination": {"place_id": 395}, "conditions": []},
            {"origin": {"place_id": 394}, "destination": {"place_id": 397}, "conditions": []},
        ]
        either_to_b = ObservationFilter.from_mapping({"destination_place_id": 395, "result_endpoint": "either"})
        self.assertFalse(either_to_b.matches(394, multiple))
        self.assertTrue(either_to_b.matches(395, multiple))
        self.assertTrue(either_to_b.matches(396, multiple))

    def test_search_never_infers_ease_or_accepts_invalid_direction_fields(self) -> None:
        for condition in ({"easy": True}, {"destination_place_id": True},
                          {"destination_place_id": 395, "content_kinds": ["landscape"]}):
            with self.assertRaises(ValueError):
                ObservationFilter.from_mapping(condition)
        self.assertIsNone(ObservationFilter.from_mapping(None))
        self.assertIsNone(ObservationFilter.from_mapping({"content_kinds": []}))

    def test_boundaries_preserve_route_and_source_without_splitting_place_names(self) -> None:
        item = observation_bundle().sources[0]
        spans = split_source(item, splitter_version=SplitterVersion.SENTENCE)
        quotes = [item.text[start:end] for start, end in spans]
        self.assertEqual(len(quotes), 3)
        self.assertEqual("".join(quotes), TEXT)
        self.assertIn("A공원", quotes[1])
        self.assertIn("B공원", quotes[1])
        self.assertIn("계단", quotes[1])
        self.assertNotIn("전망", quotes[1])
        long = type(item)(item.source_id, item.source_type, item.title, "가" * 801, item.metadata)
        with self.assertRaisesRegex(ValueError, "임의 절단"):
            split_source(long, splitter_version=SplitterVersion.SENTENCE)

    def test_topic_is_separate_from_subject_and_route_retrieves_from_both_endpoints(self) -> None:
        value = observation_bundle()
        chunks = parsed(observation_response(value), value)
        scene, route, parking = chunks
        self.assertEqual(route.content_kind, ContentKind.MOVEMENT)
        self.assertEqual([chunk.chunk_id for chunk in select_active(394, chunks)], [scene.chunk_id, route.chunk_id])
        self.assertEqual([chunk.chunk_id for chunk in select_active(395, chunks)], [route.chunk_id, parking.chunk_id])
        self.assertEqual(route.to_dict()["relations"][0]["conditions"], [{"kind": "stairs", "quote": "계단"}])
        self.assertNotIn("easy", json.dumps(route.to_dict()))
        self.assertEqual(SearchChunk.from_mapping(route.source, route.to_dict()), route)
        legacy = SearchChunk(route.source, route.start, route.end, route.context_text, route.place_refs, route.generation)
        self.assertNotEqual(route.chunk_id, legacy.chunk_id)

    def test_unknown_ids_wrong_names_and_invented_movement_conditions_are_rejected(self) -> None:
        value = observation_bundle()
        for mutation in ("id", "name", "quote", "missing_subject", "facility_relation"):
            with self.subTest(mutation=mutation):
                raw = observation_response(value)
                document = json.loads(raw["output"][0]["content"][0]["text"])
                route = document["chunks"][1]
                if mutation == "id":
                    route["relations"][0]["origin"]["place_id"] = 999
                if mutation == "name":
                    route["relations"][0]["origin"]["name"] = "다른공원"
                if mutation == "quote":
                    route["relations"][0]["conditions"][0]["quote"] = "평탄하고 쉬운 길"
                if mutation == "missing_subject":
                    route["place_refs"][0]["role"] = "mentioned"
                if mutation == "facility_relation":
                    route["content_kind"] = "facility"
                raw["output"][0]["content"][0]["text"] = json.dumps(document)
                with self.assertRaises(ValueError):
                    parsed(raw, value)

    def test_missing_origin_id_is_not_replaced_by_the_destination_id(self) -> None:
        value = observation_bundle()
        raw = observation_response(value)
        value = SourceBundle([B], value.sources)
        document = json.loads(raw["output"][0]["content"][0]["text"])
        document["chunks"][0].update(place_refs=[], entities=[])
        route = document["chunks"][1]
        route["relations"][0]["origin"]["place_id"] = None
        route["place_refs"] = route["place_refs"][1:]
        route["entities"] = route["entities"][1:]
        raw["output"][0]["content"][0]["text"] = json.dumps(document)
        chunks = parsed(raw, value)
        self.assertEqual(chunks[0].relations[0]["origin"]["place_id"], None)
        self.assertEqual(select_active(394, chunks), [])

    async def test_bad_attribution_is_quarantined_without_dropping_valid_observations(self) -> None:
        value = observation_bundle()
        raw = observation_response(value)
        document = json.loads(raw["output"][0]["content"][0]["text"])
        document["chunks"][0]["place_refs"][0]["place_id"] = 999
        document["chunks"][1].update(place_refs=[], entities=[], relations=[])
        raw["output"][0]["content"][0]["text"] = json.dumps(document)
        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                path = await collect_bundle(value, SETTINGS, Path(directory), client,
                    prompt_version=PromptVersion.V6, input_version=InputVersion.EXPLICIT,
                    splitter_version=SplitterVersion.SENTENCE)
            _, chunks, record = load_record(path)
            self.assertEqual(len(chunks), 1)
            self.assertEqual(chunks[0].content_kind, "facility")
            self.assertEqual([row["exclusion_reason"] for row in record["excluded_chunks"]],
                             ["invalid_attribution", "unresolved_movement"])
            self.assertEqual(json.loads(path.with_name("raw_response.json").read_text()), raw)

    async def test_new_archive_revalidates_and_unreviewed_apply_never_opens_database(self) -> None:
        value = observation_bundle()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=observation_response(value)))) as client:
                path = await collect_bundle(value, SETTINGS, root / "records", client,
                    prompt_version=PromptVersion.V6, input_version=InputVersion.EXPLICIT,
                    splitter_version=SplitterVersion.SENTENCE)
            _, chunks, record = load_record(path)
            self.assertEqual(record["splitter_version"], SplitterVersion.SENTENCE)
            replay = revalidate_record(path, root / "replay")
            self.assertEqual(len(load_record(replay)[1]), 3)
            pool = MagicMock()
            with self.assertRaisesRegex(ValueError, "검수 목록"):
                await apply_bundle(pool, path)
            pool.acquire.assert_not_called()
            review = root / "approval.json"
            review.write_text(json.dumps(approval_document(path, [chunk.chunk_id for chunk in chunks], "모의 검수")), encoding="utf-8")
            self.assertEqual(reviewed_chunks(path, review), chunks)
            self.assertEqual(len(selection_report(path, review)["places"][1]["selected_chunk_ids"]), 2)
            connection = AsyncMock()
            await preserve_chunks(connection, chunks)
            inserts = [call for call in connection.execute.call_args_list if "INSERT INTO retrieval_chunks(" in call.args[0]]
            self.assertTrue(inserts)
            self.assertTrue(all(call.args[-1] == SplitterVersion.SENTENCE for call in inserts))
            empty_review = root / "empty-approval.json"
            empty_review.write_text(json.dumps(approval_document(path, [], "모의 보류")), encoding="utf-8")
            self.assertEqual(await apply_bundle(pool, path, review_path=empty_review), "NO_INDEXABLE_CHUNKS")
            pool.acquire.assert_not_called()
            corrupted = json.loads(review.read_text())
            corrupted["file_sha256"]["raw_response.json"] = "wrong"
            review.write_text(json.dumps(corrupted), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "원문·응답"):
                reviewed_chunks(path, review)

    def test_cap_preserves_unselected_chunks_and_is_independent_for_each_endpoint(self) -> None:
        value = observation_bundle()
        scene, route, parking = parsed(observation_response(value), value)
        many = [SearchChunk(scene.source, scene.start, scene.end, f"문맥 {index}", scene.place_refs, {},
                splitter_version=SplitterVersion.SENTENCE, content_kind="landscape") for index in range(25)]
        # 같은 원문은 상한을 차지하지 않으며 관계 청크는 각 핵심 장소의 후보가 된다.
        self.assertEqual(len(select_active(394, many + [route])), 2)
        self.assertEqual(select_active(395, many + [route, parking]), [route, parking])
        distinct = []
        for index in range(25):
            source = normalize_source({"source_type": "review", "title": "후기", "text": f"시설 {index}를 방문했다.",
                "metadata": {"source_url": f"https://example.org/{index}", "capture_scope": "full_text"}})
            distinct.append(SearchChunk(source, 0, len(source.text), "시설 방문", [{"place_id": 395, "role": "subject"}], {},
                splitter_version=SplitterVersion.SENTENCE, content_kind="facility"))
        self.assertEqual(len(select_active(395, distinct)), 20)
        self.assertEqual(len(distinct), 25)


if __name__ == "__main__":
    unittest.main()
