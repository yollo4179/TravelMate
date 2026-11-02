"""Offline contract regressions; synthetic receipts are never benchmark observations."""
from __future__ import annotations

import asyncio
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, digest, export_inputs, read_json, read_jsonl, write_json, write_jsonl
from common.execution.control import ExecutionBlocked, ExecutionSettings, Operation, RunControl, RunMode
from common.judge.settings import JudgeSettings
from common.observability.search_records import search_quality_observed, search_record_error
from common.paths import DEFAULT_DATASET
from common.runs.runner import evaluate
from common.runs.tracks import Track
from tracks.search.api_contract import RankingMode, search_body, unsupported_conditions
from tracks.search.collect_live import collect_cases, latency_summary, request_search
from tracks.search.holdout import check_frozen, read_cases
from tracks.search.inspect_holdout_runtime import MATERIAL_SECTIONS, compare_runtime
from tracks.search.score_ranking import score_search_api_record


class SearchToolCleanupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.case = next(case for case in read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl") if "search" in case["evaluation_tracks"] and not case["input"]["conditions"].get("conversation"))
        corpus = {place["id"]: place for place in read_json(DEFAULT_DATASET / "generated/corpus.json")}
        cls.exported = export_inputs([cls.case], corpus, persona_profile=read_json(DEFAULT_DATASET / "source/persona/guide_v1.json"))[0]

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.network = patch("httpx.AsyncClient.send", side_effect=AssertionError("Offline regression attempted HTTP I/O"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def settings(self, *, cap: int = 1, mode: str = "MOCK", parameters: dict | None = None, timeout: float = 1) -> ExecutionSettings:
        configuration = self.directory / "configuration.json"
        write_json(configuration, {"mode": mode, "case_ids": [self.case["case_id"]], "max_calls": {"search": cap}, "timeout_seconds": timeout, "model": None, "max_output_tokens": None, "parameters": parameters or {}})
        return ExecutionSettings.load(configuration)

    def request(self, case: dict | None = None, mode: RankingMode = RankingMode.RERANKED) -> dict:
        body = search_body(case or self.case, mode, 20)
        raw = json.dumps(body, ensure_ascii=False, separators=(",", ":"))
        return {"method": "POST", "url": "http://evaluation.invalid/api/places/search", "route": "/api/places/search", "raw_body": raw, "body_sha256": hashlib.sha256(raw.encode()).hexdigest()}

    def control(self, response: dict, *, cap: int = 1, mode: str = "MOCK") -> RunControl:
        return RunControl(self.settings(cap=cap, mode=mode), self.directory / "attempts.jsonl", mock_responses={canonical_digest(self.request()): {"response": response}})

    def observe(self, control: RunControl, *, client: object = None, mode: RankingMode = RankingMode.RERANKED, case: dict | None = None) -> dict:
        return asyncio.run(request_search(client, case=case or self.case, input_sha256=self.exported["input_sha256"], mode=mode, control=control, server_url="http://evaluation.invalid", limit=20, runtime={}))

    def test_frozen_dependency_versions_and_bytes_are_unchanged(self) -> None:
        for version, count in (("search-holdout-v1.0.0", 80), ("search-holdout-v1.0.1", 73)):
            dataset = DEFAULT_DATASET.parent / version
            self.assertEqual(check_frozen(dataset)["case_count"], count)
            self.assertFalse(check_frozen(dataset)["human_judgments_complete"])

    def test_all_filters_use_independent_post_without_plan_context(self) -> None:
        case = copy.deepcopy(self.case)
        case["input"]["conditions"].update(region="서울", city="종로", category="관광지", exclude_place_ids=[378], area={"type": "circle", "center": {"latitude": 37.57, "longitude": 126.98}, "radius_meters": 1500, "distance_method": "haversine_straight_line"})
        body = search_body(case, RankingMode.SEMANTIC_ONLY, 20)
        self.assertEqual(body["region"], "서울")
        self.assertEqual(body["city"], "종로")
        self.assertEqual(body["category"], "관광지")
        self.assertEqual(body["excludePlaceIds"], [378])
        self.assertEqual(body["area"]["radiusMeters"], 1500)
        self.assertFalse({"planningRequest", "context", "searchContext"} & body.keys())

    def test_query_is_not_guessed_and_invalid_radius_is_not_clamped(self) -> None:
        for query in (None, "", " ", "x" * 2001):
            case = copy.deepcopy(self.case)
            case["input"]["query"] = query
            with self.subTest(query_length=len(query or "")), self.assertRaises(ValueError):
                search_body(case, RankingMode.RERANKED, 20)
        case = copy.deepcopy(self.case)
        case["input"]["conditions"]["area"] = {"center": {"latitude": 37.57, "longitude": 126.98}, "radius_meters": 499}
        with self.assertRaises(ValueError):
            search_body(case, RankingMode.RERANKED, 20)

    def test_mock_preserves_original_evidence_and_never_dispatches(self) -> None:
        original = "과거에는 연결됐지만 현재 통행은 확인되지 않았다.\u2028" * 100
        items = [{"placeId": 378, "evidenceChunks": [{"originalText": original, "sourceId": "synthetic-source", "relations": [{"origin": {"placeId": 378}, "destination": {"placeId": 365}, "condition": "공사 중 통행 불가"}]}]}]
        control = self.control({"status_code": 200, "raw_body": json.dumps(items, ensure_ascii=False)})
        client = AsyncMock()
        record = self.observe(control, client=client)
        client.request.assert_not_awaited()
        self.assertEqual(record["items"], items)
        self.assertEqual(record["execution_status"], "completed")
        self.assertFalse(record["dispatched"])
        self.assertEqual(record["execution_mode"], "MOCK")
        self.assertIsNone(search_record_error(self.case, record))
        self.assertFalse(search_quality_observed(record))
        self.assertTrue(all(value is None for value in score_search_api_record(self.case, record)["metrics"].values()))
        self.assertEqual(latency_summary([record])["successful_live_count"], 0)

    def test_http_failure_and_invalid_json_preserve_raw_failure(self) -> None:
        for response in ({"status_code": 400, "raw_body": '{"error":"invalid query"}'}, {"status_code": 200, "raw_body": "not-json"}):
            with self.subTest(response=response):
                directory = self.directory / str(response["status_code"])
                control = RunControl(self.settings(), directory / "attempts.jsonl", mock_responses={canonical_digest(self.request()): {"response": response}})
                record = self.observe(control)
                self.assertEqual(record["execution_status"], "failed")
                self.assertEqual(record["http_response"], response)
                self.assertIsNone(record["ranked_place_ids"])
                self.assertTrue(control.stopped)

    def test_genuinely_empty_success_is_distinct_from_failure(self) -> None:
        record = self.observe(self.control({"status_code": 200, "raw_body": "[]"}))
        self.assertEqual(record["execution_status"], "completed")
        self.assertEqual(record["ranked_place_ids"], [])

    def test_cap_block_is_unexecuted_and_restart_cannot_reset_ledger(self) -> None:
        control = self.control({"status_code": 200, "raw_body": "[]"}, cap=0)
        record = self.observe(control)
        self.assertEqual(record["execution_status"], "not_run")
        self.assertFalse(record["dispatched"])
        self.assertIsNone(record["http_response"])
        with self.assertRaises(FileExistsError):
            RunControl(control.settings, control.ledger_path)

    def test_timeout_spends_one_attempt_and_stops_without_retry(self) -> None:
        control = RunControl(self.settings(mode="LIVE", timeout=0.01), self.directory / "attempts.jsonl")
        async def delayed() -> dict:
            await asyncio.sleep(0.1)
            return {}
        with self.assertRaises(TimeoutError):
            asyncio.run(control.execute(Operation.SEARCH, self.case["case_id"], {}, delayed))
        self.assertEqual(control.counts[Operation.SEARCH], 1)
        self.assertTrue(control.stopped)
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(control.execute(Operation.SEARCH, self.case["case_id"], {}, delayed))
        self.assertEqual(control.counts[Operation.SEARCH], 1)

    def test_unsupported_history_is_not_claimed_applied(self) -> None:
        case = copy.deepcopy(self.case)
        case["input"]["conditions"]["conversation"] = [{"role": "user", "content": "이전 질문"}]
        control = self.control({"status_code": 200, "raw_body": "[]"})
        record = self.observe(control, case=case)
        self.assertEqual(record["execution_status"], "not_run")
        self.assertEqual(record["unsupported_conditions"], ["conversation"])
        self.assertEqual(control.counts[Operation.SEARCH], 0)

    def test_original_request_and_response_tampering_is_rejected(self) -> None:
        record = self.observe(self.control({"status_code": 200, "raw_body": '[{"placeId":378}]'}))
        record["items"][0]["placeId"] = 365
        self.assertEqual(search_record_error(self.case, record), "search_response_provenance_mismatch")
        legacy = {"record_source": "spring_search_api", "ranked_place_ids": [378], "http_status": 200}
        self.assertEqual(search_record_error(self.case, legacy), "legacy_search_record_requires_explicit_adaptation")

    def test_search_mock_and_failed_observations_never_construct_a_judge(self) -> None:
        record = self.observe(self.control({"status_code": 200, "raw_body": "[]"}))
        responses = self.directory / "records.jsonl"
        write_jsonl(responses, [record])
        with patch("openai.AsyncOpenAI", side_effect=AssertionError("No paid judge client is allowed")):
            result = asyncio.run(evaluate(root=DEFAULT_DATASET, group=None, cases=[self.case], responses_path=responses, output=self.directory / "scores", use_judge=True, settings=JudgeSettings("unused", ""), track=Track.SEARCH))
        summary = read_json(self.directory / "scores/summary.json")
        scored = read_jsonl(self.directory / "scores/scores/results.jsonl")[0]
        self.assertEqual(result, 1)
        self.assertEqual(summary["search_quality_evaluated_count"], 0)
        self.assertEqual(summary["type_confusion"], {})
        self.assertEqual(scored["judge_status"], "not_evaluated")
        self.assertIsNone(scored["tool_calls"])

    def test_config_is_explicit_and_rejects_unknown_operations_and_boolean_caps(self) -> None:
        self.settings()
        path = self.directory / "configuration.json"
        for name, value in (("case_ids", []), ("max_calls", {"search": True}), ("max_calls", {"typo": 1}), ("timeout_seconds", 0)):
            configuration = read_json(path)
            configuration[name] = value
            write_json(path, configuration)
            with self.subTest(field=name, value=value), self.assertRaises((ValueError, TypeError)):
                ExecutionSettings.load(path)
            self.settings()

    def test_collect_preserves_unexecuted_modes_after_first_failure(self) -> None:
        parameters = {"ranking_modes": ["RERANKED", "SEMANTIC_ONLY"], "dataset_manifest_sha256": digest(DEFAULT_DATASET / "manifest.json"), "server_url": "http://evaluation.invalid", "response_limit": 20, "require_comparable_runtime": False}
        settings = self.settings(cap=2, parameters=parameters)
        control = RunControl(settings, self.directory / "attempts.jsonl", mock_responses={canonical_digest(self.request()): {"response": {"status_code": 500, "raw_body": "server failure"}}})
        case = {**self.case, "input_sha256": self.exported["input_sha256"]}
        asyncio.run(collect_cases(cases=[case], dataset=DEFAULT_DATASET, output=self.directory, control=control, runtime={"corpus_sha256": digest(DEFAULT_DATASET / "generated/corpus.json")}))
        self.assertEqual(read_jsonl(self.directory / "reranked_records.jsonl")[0]["execution_status"], "failed")
        self.assertEqual(read_jsonl(self.directory / "embedding_records.jsonl")[0]["execution_status"], "not_run")
        self.assertEqual(control.counts[Operation.SEARCH], 1)


class RuntimeComparisonTests(unittest.TestCase):
    def fixture(self) -> dict:
        protocol = read_json(DEFAULT_DATASET.parent / "search-holdout-v1.0.1/protocol.json")
        place = read_json(DEFAULT_DATASET / "generated/corpus.json")[0]
        material = {section: [] for section in MATERIAL_SECTIONS}
        material["places"] = [{**place, "place_id": place["id"], "document_status": "READY"}]
        material["place_vectors"] = [{"place_id": place["id"], "dimension": 1024, "embedding_md5": "synthetic-vector-fingerprint"}]
        metadata = {"health": {"status": "ok", "cuda_available": True, "embedding_parameter_device": "cuda:0", "reranker_parameter_device": "cuda:0", "reranker_execution_strategy": "autocast_fp16", "reranker_configured_batch_size": 8, "reranker_effective_batch_size": 8}, "search_source_sha256": "synthetic-source-hash", "source_files_sha256": {"config.py": "synthetic-source-hash"}, "configured_models": {"MODEL_NAME_EMBEDDING": "BAAI/bge-m3", "MODEL_NAME_RERANKER": "BAAI/bge-reranker-v2-m3"}, "cached_revisions": {"models--BAAI--bge-m3": "synthetic-revision", "models--BAAI--bge-reranker-v2-m3": "synthetic-revision"}}
        targets = {"embedding_container": "synthetic-evaluation", "postgres_container": "synthetic-db"}
        return {"corpus": [place], "protocol": protocol, "capture": {"execution_mode": "MOCK", "targets": targets, "search_material": material, "metadata": metadata}, "expected_material": copy.deepcopy(material), "expected_configuration": copy.deepcopy(metadata), "expected_targets": targets, "corpus_sha256": digest(DEFAULT_DATASET / "generated/corpus.json")}

    def test_mock_match_does_not_become_live_runtime_verification(self) -> None:
        result = compare_runtime(**self.fixture())
        self.assertTrue(all(result["comparison_checks"].values()))
        self.assertFalse(result["corpus_verified"])
        self.assertFalse(result["configuration_verified"])
        self.assertFalse(result["search_material_verified"])

    def test_same_place_ids_with_changed_text_or_relation_material_are_not_equivalent(self) -> None:
        arguments = self.fixture()
        arguments["capture"]["search_material"]["places"][0]["description"] = "different original"
        result = compare_runtime(**arguments)
        self.assertFalse(result["comparison_checks"]["corpus_matches"])
        self.assertFalse(result["comparison_checks"]["search_material_matches"])
        arguments = self.fixture()
        arguments["capture"]["search_material"]["relations"] = [{"evidence": {"text": "different condition"}}]
        self.assertFalse(compare_runtime(**arguments)["comparison_checks"]["search_material_matches"])

    def test_actual_cpu_device_or_missing_observation_is_not_gpu_verification(self) -> None:
        for value in ("cpu", None):
            arguments = self.fixture()
            arguments["capture"]["metadata"]["health"]["reranker_parameter_device"] = value
            arguments["expected_configuration"]["health"]["reranker_parameter_device"] = value
            self.assertFalse(compare_runtime(**arguments)["comparison_checks"]["configuration_matches"])


if __name__ == "__main__":
    unittest.main()
