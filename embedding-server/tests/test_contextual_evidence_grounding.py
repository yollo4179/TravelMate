"""인용의 유일 일치·원문 좌표·기존 아카이브 호환성을 검증한다."""
from __future__ import annotations

from copy import deepcopy
import json
import argparse
from pathlib import Path
import sys
import tempfile
from typing import Any
import unittest
from unittest.mock import patch

import httpx
from jsonschema import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from app.contextual.agent import parse_chunks, request_payload, schema_for_prompt
from app.contextual.artifacts import collect_bundle, load_record, revalidate_record
from app.contextual.contracts import SplitterVersion
from app.contextual.evidence_grounding import GroundingStatus, GroundingVersion, ground_relation_evidence
from app.contextual.input_format import InputVersion
from app.contextual.observation_search import ObservationFilter
from app.contextual.prompts import DEFAULT_PROMPT_VERSION, PromptVersion, resolve_prompt
from app.contextual.validation import ValidationVersion, resolve_validation_version
from app.contextual.replay import GenerationBaseline
from app.contextual.cli import run
from test_contextual_chunks import SETTINGS
from test_contextual_supporting_relations import fixture, rows, changed, TEXT, QUOTE


def grounding_row(text: str, quote: str, start: int = 0, end: int | None = None) -> dict[str, Any]:
    return {"source_id": "source", "start": start, "end": len(text) if end is None else end,
            "relations": [{"evidence": {"quote": quote}}]}


class EvidenceGroundingTests(unittest.IsolatedAsyncioTestCase):
    def test_unique_quote_replaces_wrong_model_positions_without_mutation(self) -> None:
        row = grounding_row(TEXT, QUOTE)
        row["relations"][0]["evidence"].update(start=16, end=35)
        original = deepcopy(row)
        result = ground_relation_evidence(row, TEXT)
        self.assertIsNone(result.error)
        self.assertEqual(result.chunk["relations"][0]["evidence"], {"start": 15, "end": 35, "quote": QUOTE})
        self.assertEqual(row, original)
        self.assertEqual(result.audit[0]["model_evidence"], original["relations"][0]["evidence"])
        self.assertEqual(result.audit[0]["server_span"], {"start": 15, "end": 35})
        self.assertEqual(result.audit[0]["rule_version"], GroundingVersion.EXACT_UNIQUE)

    def test_nonzero_source_offset_and_exact_whitespace_newline_emoji(self) -> None:
        prefix = "앞부분😀\n"
        quote = "😀 A공원  → B공원\r\n도보 이동"
        text = prefix + quote + "\n뒷부분"
        row = grounding_row(text, quote, len(prefix), len(prefix) + len(quote))
        result = ground_relation_evidence(row, text)
        self.assertIsNone(result.error)
        evidence = result.chunk["relations"][0]["evidence"]
        self.assertEqual(evidence["start"], len(prefix))
        self.assertEqual(text[evidence["start"]:evidence["end"]], quote)

    def test_absent_other_chunk_and_cross_boundary_quotes_are_held(self) -> None:
        text = "첫 청크 도보 이동. 다음 청크 주차장."
        end = text.index(" 다음")
        for quote in ("없는 문장", "다음 청크 주차장.", "이동. 다음"):
            with self.subTest(quote=quote):
                result = ground_relation_evidence(grounding_row(text, quote, 0, end), text)
                self.assertEqual(result.audit[0]["status"], GroundingStatus.NOT_FOUND)
                self.assertIsNone(result.audit[0]["server_span"])
                self.assertIsNotNone(result.error)

    def test_repeated_and_overlapping_matches_are_held_without_using_model_position(self) -> None:
        for text, quote in (("도보 이동 / 도보 이동", "도보 이동"), ("aaaa", "aaa")):
            row = grounding_row(text, quote)
            row["relations"][0]["evidence"].update(start=0, end=len(quote))
            result = ground_relation_evidence(row, text)
            self.assertEqual(result.audit[0]["status"], GroundingStatus.AMBIGUOUS)
            self.assertIsNone(result.audit[0]["server_span"])

    def test_repetition_outside_current_chunk_does_not_create_ambiguity(self) -> None:
        text = "도보 이동 / 도보 이동"
        result = ground_relation_evidence(grounding_row(text, "도보 이동", 0, 5), text)
        self.assertIsNone(result.error)
        self.assertEqual(result.audit[0]["server_span"], {"start": 0, "end": 5})

    def test_no_trimming_normalization_or_fuzzy_repair(self) -> None:
        for text, quote in (("A  B", "A B"), ("A\r\nB", "A\nB"), ("é", "e\u0301"), ("도보 이동", "도보  이동")):
            result = ground_relation_evidence(grounding_row(text, quote), text)
            self.assertEqual(result.audit[0]["status"], GroundingStatus.NOT_FOUND)
        for quote in ("", " \r\n"):
            result = ground_relation_evidence(grounding_row("공원", quote), "공원")
            self.assertEqual(result.audit[0]["status"], GroundingStatus.EMPTY)

    def test_invalid_chunk_coordinates_are_not_clamped(self) -> None:
        for start, end in ((-1, 1), (0, 100), (True, 2), (2, 1)):
            with self.assertRaises(ValueError):
                ground_relation_evidence(grounding_row("공원 이동", "이동", start, end), "공원 이동")

    def test_v7_default_stays_strict_but_explicit_v5_recovers_correct_quote(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["relations"][0]["evidence"]["start"] = 16
        raw = changed(raw, document)
        options = {"prompt_version": PromptVersion.V7, "splitter_version": SplitterVersion.SENTENCE}
        self.assertEqual(parse_chunks(raw, bundle.places, bundle.sources, **options), [])
        chunk, = parse_chunks(raw, bundle.places, bundle.sources, validation_version=ValidationVersion.SERVER_EVIDENCE, **options)
        self.assertEqual(chunk.relations[0]["evidence"]["start"], 15)
        self.assertEqual(chunk.subject_place_ids, {394})
        self.assertEqual(chunk.place_refs[1]["role"], "mentioned")
        self.assertTrue(ObservationFilter.from_mapping({"destination_place_id": 395}).matches(394, chunk.to_dict()))
        self.assertFalse(ObservationFilter.from_mapping({"content_kinds": ["landscape"]}).matches(395, chunk.to_dict()))

    def test_v8_request_asks_quote_only_and_keeps_immutable_chunk_coordinates(self) -> None:
        bundle, _ = fixture()
        payload = request_payload(bundle.places, bundle.sources, SETTINGS, prompt_version=PromptVersion.V8,
                                  input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
        evidence = payload["response_format"]["json_schema"]["schema"]["properties"]["chunks"]["items"]["properties"]["relations"]["items"]["properties"]["evidence"]
        self.assertEqual(set(evidence["properties"]), {"quote"})
        self.assertEqual(evidence["required"], ["quote"])
        self.assertFalse(evidence["additionalProperties"])
        self.assertIn("Do NOT return or calculate evidence.start/end", payload["instructions"])
        self.assertNotIn("absolute Unicode start/end offsets", payload["instructions"])
        self.assertEqual(json.loads(payload["input"])["spans"][0]["chunk_text"], TEXT)
        self.assertEqual(payload["tools"], [])
        self.assertEqual(DEFAULT_PROMPT_VERSION, PromptVersion.V2)
        self.assertEqual(resolve_validation_version(None, PromptVersion.V8), ValidationVersion.SERVER_EVIDENCE)
        with self.assertRaises(ValueError):
            resolve_validation_version(ValidationVersion.RELATIONS, PromptVersion.V8)
        with self.assertRaises(ValueError):
            resolve_validation_version(ValidationVersion.SERVER_EVIDENCE, PromptVersion.V6)

    def test_v7_to_v8_is_rejected_as_prompt_only_comparison(self) -> None:
        bundle, _ = fixture()
        payload = request_payload(bundle.places, bundle.sources, SETTINGS, prompt_version=PromptVersion.V7,
                                  input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
        baseline = GenerationBaseline(bundle, payload, {"prompt_version": PromptVersion.V7,
                                       "input_version": InputVersion.EXPLICIT}, "mock", "mock")
        with self.assertRaises(ValueError):
            baseline.candidate_request(PromptVersion.V8)

    async def test_explicit_version_on_directory_revalidation_fails_without_empty_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            args = argparse.Namespace(command="revalidate", record=Path(directory),
                                      validation_version=ValidationVersion.SERVER_EVIDENCE)
            with self.assertRaises(ValueError):
                await run(args)

    def test_v8_quote_only_response_is_grounded_before_storage_validation(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["relations"][0]["evidence"] = {"quote": QUOTE}
        chunk, = parse_chunks(changed(raw, document), bundle.places, bundle.sources,
                              prompt_version=PromptVersion.V8, splitter_version=SplitterVersion.SENTENCE)
        self.assertEqual(chunk.relations[0]["evidence"], {"start": 15, "end": 35, "quote": QUOTE})
        with self.assertRaises(ValidationError):
            parse_chunks(raw, bundle.places, bundle.sources, prompt_version=PromptVersion.V8,
                         splitter_version=SplitterVersion.SENTENCE)
        self.assertEqual(set(schema_for_prompt(PromptVersion.V7)["properties"]["chunks"]["items"]["properties"]["relations"]["items"]["properties"]["evidence"]["properties"]), {"start", "end", "quote"})

    def test_relation_failure_still_quarantines_parent_observation(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["relations"][0]["evidence"]["quote"] = "다른 청크의 이동"
        self.assertEqual(parse_chunks(changed(raw, document), bundle.places, bundle.sources,
                                     prompt_version=PromptVersion.V7, splitter_version=SplitterVersion.SENTENCE,
                                     validation_version=ValidationVersion.SERVER_EVIDENCE), [])

    async def test_revalidate_preserves_all_original_files_and_detects_audit_tampering(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["relations"][0]["evidence"]["start"] = 16
        raw = changed(raw, document)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                source = await collect_bundle(bundle, SETTINGS, root / "original", client, prompt_version=PromptVersion.V7,
                                              input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
            originals = {name: source.with_name(name).read_bytes() for name in ("record.json", "request.json", "sources.json", "raw_response.json")}
            self.assertEqual(load_record(source)[1], [])
            with patch("httpx.AsyncClient", side_effect=AssertionError("재처리 HTTP 클라이언트 생성 금지")):
                result = revalidate_record(source, root / "processed", validation_version=ValidationVersion.SERVER_EVIDENCE)
            _, chunks, record = load_record(result)
            self.assertEqual(len(chunks), 1)
            self.assertEqual(record["api_calls"], 0)
            self.assertEqual(record["evidence_grounding"][0]["model_evidence"]["start"], 16)
            self.assertEqual(record["evidence_grounding"][0]["server_span"]["start"], 15)
            self.assertEqual(originals, {name: source.with_name(name).read_bytes() for name in originals})
            for name in ("request.json", "sources.json", "raw_response.json"):
                self.assertEqual(result.with_name(name).read_bytes(), originals[name])
            record["evidence_grounding"][0]["server_span"]["start"] = 16
            result.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_record(result)

    async def test_unmatched_quote_preserves_model_evidence_and_exclusion_reason(self) -> None:
        bundle, raw = fixture()
        document = rows(raw)
        document["chunks"][0]["relations"][0]["evidence"] = {"quote": "다른 청크의 이동"}
        raw = changed(raw, document)
        with tempfile.TemporaryDirectory() as directory:
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(200, json=raw))) as client:
                path = await collect_bundle(bundle, SETTINGS, Path(directory), client, prompt_version=PromptVersion.V8,
                                            input_version=InputVersion.EXPLICIT, splitter_version=SplitterVersion.SENTENCE)
            _, chunks, record = load_record(path)
            self.assertEqual(chunks, [])
            self.assertEqual(record["evidence_grounding"][0]["status"], GroundingStatus.NOT_FOUND)
            self.assertIsNone(record["evidence_grounding"][0]["server_span"])
            self.assertEqual(record["excluded_chunks"][0]["validation_error"], GroundingStatus.NOT_FOUND)


if __name__ == "__main__":
    unittest.main()
