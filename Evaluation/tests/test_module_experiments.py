"""Module/transport regressions only. No application, model or database is started."""
from __future__ import annotations

import asyncio
import copy
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.io import canonical_digest, digest, read_json, write_json
from common.execution.control import ExecutionBlocked
from common.experiments.contracts import ExperimentConfig, ModuleConfig, ModuleInput, ModuleKind, ModuleRegistry
from common.experiments.modules import ConversationApiModule, DEFAULT_MODULES, SearchApiModule
from common.experiments.runner import prepare, run_experiment
from common.experiments.server import isolated_environment, main as server_main, validate_environment
from common.paths import DEFAULT_DATASET
from tracks.search.collect_live import selected_v14_inputs


class ModuleExperimentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.directory = Path(self.temporary.name)
        self.profile = {"search": "existing-search", "evidence": "original", "llm": "offline-fixture", "prompt": "existing"}
        self.case_ids = ["PLR-TM-palaces-01", "PLR-TM-palaces-03"]
        self.cases = selected_v14_inputs(DEFAULT_DATASET, tuple(self.case_ids))
        self.configuration = self.directory / "experiment.json"
        self.fixture_path = self.directory / "fixtures.json"
        self.runtime_path = self.directory / "runtime.json"
        write_json(self.runtime_path, {"environment": "evaluation", "execution_mode": "MOCK",
                   "server_url": "http://127.0.0.1:18080", "backend_profile": self.profile,
                   "corpus_sha256": digest(DEFAULT_DATASET / "generated/corpus.json")})
        self.document = {"schema_version": "module-experiment-v1", "dataset": str(DEFAULT_DATASET),
                         "dataset_manifest_sha256": digest(DEFAULT_DATASET / "manifest.json"),
                         "server_url": "http://127.0.0.1:18080", "token_env": "EVAL_TEST_TOKEN",
                         "runtime_record": "runtime.json", "runtime_sha256": digest(self.runtime_path),
                         "fixtures": "fixtures.json", "variants": [self.variant("semantic", "SEMANTIC_ONLY"), self.variant("reranked", "RERANKED")],
                         "execution": {"mode": "MOCK", "case_ids": self.case_ids, "max_calls": {"search": 4},
                                       "timeout_seconds": 1, "model": None, "max_output_tokens": None, "parameters": {}}}
        self.network = patch("httpx.AsyncClient", side_effect=AssertionError("Offline test constructed a network client"))
        self.network.start()
        self.addCleanup(self.network.stop)

    def variant(self, identifier: str, ranking: str | None) -> dict:
        return {"id": identifier, "module": "SEARCH_API" if ranking else "CONVERSATION_API",
                "ranking_mode": ranking, "response_limit": 5 if ranking else None,
                "expected_response_type": "PLACES" if ranking is None else None,
                "require_citations": ranking is None, "backend_profile": self.profile}

    def config(self) -> ExperimentConfig:
        write_json(self.configuration, self.document)
        return ExperimentConfig.load(self.configuration)

    def fixture(self, response: dict | None = None) -> ExperimentConfig:
        config = self.config()
        fixtures = {}
        for variant in config.variants:
            module = DEFAULT_MODULES.select(variant.kind)
            for case in self.cases:
                supplied = ModuleInput(case=case, input_sha256=case["input_sha256"], conversation_id="preview", turn_key="preview")
                request = module.request(supplied, variant, config.server_url)
                fixtures[variant.identifier + ":" + case["case_id"]] = {
                    "input_sha256": supplied.input_sha256, "body_sha256": request["body_sha256"],
                    "response": response or {"status_code": 200, "raw_body": '[{"placeId":378,"description":"원문 보존"}]'},
                }
        write_json(self.fixture_path, fixtures)
        return config

    def run_config(self, config: ExperimentConfig) -> dict:
        return asyncio.run(run_experiment(config, self.directory / "result"))

    def test_registry_rejects_missing_and_ambiguous_implementation(self) -> None:
        for registry in (ModuleRegistry(()), ModuleRegistry((SearchApiModule(), SearchApiModule()))):
            with self.assertRaises(ValueError):
                registry.select(ModuleKind.SEARCH_API)

    def test_search_variants_share_runner_and_preserve_inputs_without_clients(self) -> None:
        before = canonical_digest(self.cases)
        summary = self.run_config(self.fixture())
        self.assertEqual(summary["status"], "completed")
        self.assertEqual(summary["execution"]["attempt_counts"], {"search": 4})
        self.assertEqual(summary["execution"]["real_dispatch_count"], 0)
        self.assertEqual(canonical_digest(self.cases), before)
        scores = [json.loads(line) for line in (self.directory / "result/semantic/scores.jsonl").read_text().splitlines()]
        self.assertTrue(all(value is None for row in scores for value in row["metrics"].values()))
        self.assertEqual(summary["by_variant"]["semantic"]["latency"]["successful_live_count"], 0)
        self.assertIsNone(summary["total_billed_cost_usd"])

    def test_failed_response_stops_before_later_case_and_variant(self) -> None:
        summary = self.run_config(self.fixture({"status_code": 500, "raw_body": "original failure"}))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["execution"]["attempt_counts"], {"search": 1})
        self.assertEqual(len(summary["not_run"]), 3)
        record = json.loads((self.directory / "result/semantic/records.jsonl").read_text())
        self.assertEqual(record["http_response"]["raw_body"], "original failure")

    def test_cap_is_checked_before_output_directory_or_journal(self) -> None:
        self.document["execution"]["max_calls"]["search"] = 3
        with self.assertRaises(ExecutionBlocked):
            self.run_config(self.config())
        self.assertFalse((self.directory / "result").exists())

    def test_reusing_result_directory_is_rejected_without_resetting_ledger(self) -> None:
        config = self.fixture()
        self.run_config(config)
        ledger = self.directory / "result/attempts.jsonl"
        before = digest(ledger)
        with self.assertRaises(FileExistsError):
            self.run_config(config)
        self.assertEqual(digest(ledger), before)

    def test_changed_runtime_is_rejected_after_configuration_load(self) -> None:
        config = self.fixture()
        write_json(self.runtime_path, {"environment": "production"})
        with self.assertRaises(ExecutionBlocked):
            self.run_config(config)

    def test_fixture_body_or_input_mismatch_blocks_before_execution(self) -> None:
        for key in ("body_sha256", "input_sha256"):
            config = self.fixture()
            fixtures = read_json(self.fixture_path)
            fixtures[next(iter(fixtures))][key] = "wrong"
            write_json(self.fixture_path, fixtures)
            with self.assertRaises(ValueError):
                self.run_config(config)
        self.assertFalse((self.directory / "result").exists())

    def test_live_needs_explicit_switch_and_cannot_use_mock_runtime(self) -> None:
        self.document["execution"]["mode"] = "LIVE"
        self.document["fixtures"] = None
        config = self.config()
        with self.assertRaises(ExecutionBlocked):
            self.run_config(config)
        with self.assertRaises(ExecutionBlocked):
            asyncio.run(run_experiment(config, self.directory / "result", execute_live=True))

    def test_one_active_server_cannot_claim_two_model_profiles(self) -> None:
        self.document["variants"][1]["backend_profile"] = {"llm": "another-model"}
        with self.assertRaises(ValueError):
            self.config()

    def test_unknown_module_and_duplicate_variant_and_hidden_cap_are_rejected(self) -> None:
        for mutate in (
            lambda: self.document["variants"][0].update(module="UNKNOWN"),
            lambda: self.document["variants"][1].update(id="semantic"),
            lambda: self.document["execution"]["max_calls"].update(judge=1),
        ):
            saved = copy.deepcopy(self.document)
            mutate()
            with self.assertRaises(ValueError):
                self.config()
            self.document = saved

    def test_utf8_requests_match_original_queries_and_condition_filters(self) -> None:
        config = self.fixture()
        self.run_config(config)
        rows = [json.loads(line) for line in (self.directory / "result/requests.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(json.loads(rows[0]["request"]["raw_body"])["query"], "창경궁을 찾아줘.")
        self.assertEqual(json.loads(rows[1]["request"]["raw_body"])["city"], "종로")
        self.assertEqual(rows[0]["input_sha256"], "13f07e1370f08c3962a159bbf18ff3ef60b7a5b2d03f1d550a34c96f70f9598b")

    def test_preview_has_no_journal_or_client(self) -> None:
        prepare(self.config(), DEFAULT_MODULES)
        self.assertFalse((self.directory / "result").exists())

    def test_conversation_module_uses_one_server_call_not_a_second_search(self) -> None:
        self.document["variants"] = [self.variant("conversation", None)]
        self.document["execution"]["max_calls"] = {"conversation": 2}
        native = {"termination": "COMPLETED", "messageSource": "LLM", "modelTurns": 1,
                  "toolResults": [], "type": "PLACES", "message": "동결 원문 기반의 합성 설명",
                  "citations": [{"quote": "합성 인용"}]}
        summary = self.run_config(self.fixture({"status_code": 200, "raw_body": json.dumps(native, ensure_ascii=False)}))
        self.assertEqual(summary["execution"]["attempt_counts"], {"conversation": 2})
        self.assertIsNone(summary["internal_provider_call_counts"])
        self.assertEqual(summary["quality_status"], "mock_regression_only")
        records = [json.loads(line) for line in (self.directory / "result/conversation/records.jsonl").read_text().splitlines()]
        self.assertTrue(all(row["record_source"] == "conversation_http_experiment" for row in records))
        self.assertNotIn("tool_calls", records[0])

    def test_http200_fallback_is_failure_not_model_completion(self) -> None:
        self.document["variants"] = [self.variant("conversation", None)]
        self.document["execution"]["max_calls"] = {"conversation": 2}
        response = {"termination": "COUNT_UNAVAILABLE", "messageSource": "SERVER_FALLBACK"}
        summary = self.run_config(self.fixture({"status_code": 200, "raw_body": json.dumps(response)}))
        self.assertEqual(summary["status"], "failed")
        self.assertEqual(summary["execution"]["attempt_counts"], {"conversation": 1})

    def test_conversation_preserves_long_message_and_fresh_turn_identity(self) -> None:
        module = ConversationApiModule()
        config = ModuleConfig.load(self.variant("conversation", None))
        case = copy.deepcopy(self.cases[0])
        case["input"]["query"] = "긴 원문" * 700
        supplied = ModuleInput(case=case, input_sha256="bound", conversation_id="cid", turn_key="tid")
        request = module.request(supplied, config, "http://127.0.0.1:18080")
        self.assertEqual(json.loads(request["raw_body"])["message"], case["input"]["query"])
        self.assertEqual(request["headers"]["X-Evaluation-Input-Sha256"], "bound")
        self.assertEqual(request["headers"]["Idempotency-Key"], "tid")


class EvaluationServerTests(unittest.TestCase):
    def environment(self) -> dict[str, str]:
        return {"EVAL_DB_URL": "jdbc:postgresql://127.0.0.1:15432/travelmate_evaluation", "EVAL_DB_USERNAME": "fixture",
                "EVAL_DB_PASSWORD": "fixture-only", "EVAL_JWT_SECRET": "fixture-only-secret-with-at-least-32-bytes",
                "EVAL_REDIS_HOST": "127.0.0.1", "EVAL_REDIS_PORT": "16379",
                "EVAL_KAFKA_BOOTSTRAP_SERVERS": "127.0.0.1:39092", "EVAL_EMBEDDING_SERVER_URL": "http://127.0.0.1:18000",
                "EVAL_LLM_PROVIDER": "QWEN", "EVAL_OBSERVATION_DIRECTORY": "/tmp/evaluation-observations",
                "EVAL_PRODUCTION_DB_URL": "jdbc:postgresql://127.0.0.1:5432/travel_db",
                "EVAL_PRODUCTION_REDIS_ADDRESS": "127.0.0.1:6379", "EVAL_PRODUCTION_KAFKA_SERVERS": "127.0.0.1:29092",
                "EVAL_PRODUCTION_SERVER_PORT": "8080", "EVAL_PRODUCTION_EMBEDDING_URL": "http://127.0.0.1:8000"}

    def test_separate_evaluation_environment_needs_no_network(self) -> None:
        validate_environment(self.environment())

    def test_missing_test_setting_does_not_fall_back_to_production(self) -> None:
        environment = self.environment()
        del environment["EVAL_DB_URL"]
        environment["DB_URL"] = environment["EVAL_PRODUCTION_DB_URL"]
        with self.assertRaises(ValueError):
            validate_environment(environment)

    def test_shared_database_or_service_is_rejected(self) -> None:
        for key, production in (("EVAL_DB_URL", "EVAL_PRODUCTION_DB_URL"),
                                ("EVAL_KAFKA_BOOTSTRAP_SERVERS", "EVAL_PRODUCTION_KAFKA_SERVERS"),
                                ("EVAL_EMBEDDING_SERVER_URL", "EVAL_PRODUCTION_EMBEDDING_URL"),
                                ("EVAL_SERVER_PORT", "EVAL_PRODUCTION_SERVER_PORT")):
            environment = self.environment()
            environment[key] = environment[production]
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_environment(environment)

    def test_production_overrides_are_removed_from_child_environment(self) -> None:
        environment = {**self.environment(), "SPRING_DATASOURCE_URL": "production", "SERVER_PORT": "8080",
                       "OPENAI_API_KEY": "production-fixture", "PATH": "/usr/bin"}
        child = isolated_environment(environment)
        self.assertNotIn("SPRING_DATASOURCE_URL", child)
        self.assertNotIn("OPENAI_API_KEY", child)
        self.assertNotIn("SERVER_PORT", child)
        self.assertEqual(child["SPRING_PROFILES_ACTIVE"], "evaluation")
        self.assertEqual(child["PATH"], "/usr/bin")

    def test_existing_ledger_is_not_reused_or_deleted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            write_json(folder / "policy.json", {"ledgerFile": "ledger.jsonl", "model": "test-model"})
            (folder / "ledger.jsonl").write_text("old reservation\n")
            environment = {**self.environment(), "EVAL_LLM_PROVIDER": "OPENAI",
                           "EVAL_OPENAI_BUDGET_FILE": str(folder / "policy.json"), "EVAL_OPENAI_MODEL": "test-model"}
            with self.assertRaises(ValueError):
                validate_environment(environment)
            self.assertEqual((folder / "ledger.jsonl").read_text(), "old reservation\n")

    def test_launcher_check_never_starts_process_or_copies_runtime(self) -> None:
        with patch.dict(os.environ, self.environment(), clear=True), patch.object(sys, "argv", ["evaluation_server.py"]), patch("common.experiments.server.subprocess.run") as process:
            server_main()
            process.assert_not_called()

    def test_launcher_starts_only_shared_source_with_isolated_profile(self) -> None:
        environment = {**self.environment(), "OPENAI_API_KEY": "production-fixture", "SPRING_DATASOURCE_URL": "production"}
        with patch.dict(os.environ, environment, clear=True), patch.object(sys, "argv", ["evaluation_server.py", "--start"]), patch("common.experiments.server.subprocess.run") as process:
            server_main()
            arguments, options = process.call_args
            self.assertEqual(arguments[0][-2:], ["bootRun", "--args=--spring.profiles.active=evaluation"])
            if os.name != "nt":
                self.assertEqual(arguments[0][:2], ["bash", "./gradlew"])
            self.assertEqual(options["env"]["SPRING_PROFILES_ACTIVE"], "evaluation")
            self.assertNotIn("OPENAI_API_KEY", options["env"])
            self.assertNotIn("SPRING_DATASOURCE_URL", options["env"])

    def test_redis_and_kafka_aliases_cannot_bypass_separation_check(self) -> None:
        environment = self.environment()
        environment.update(EVAL_REDIS_HOST="localhost", EVAL_REDIS_PORT="6379")
        with self.assertRaises(ValueError):
            validate_environment(environment)
        environment = self.environment()
        environment["EVAL_KAFKA_BOOTSTRAP_SERVERS"] = "localhost:29092,localhost:39092"
        with self.assertRaises(ValueError):
            validate_environment(environment)


if __name__ == "__main__":
    unittest.main()
