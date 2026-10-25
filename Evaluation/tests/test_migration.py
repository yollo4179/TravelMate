"""Verify the file move preserves gold, input identity and runtime isolation."""
from __future__ import annotations

import asyncio
import copy
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.dataset.build import build
from common.dataset.io import digest, export_inputs, read_json, read_jsonl, write_jsonl
from common.judge.settings import JudgeSettings
from common.paths import DEFAULT_DATASET, EVALUATION_ROOT
from common.runs.run_record import allocate_run, update_latest, write_run_record
from common.runs.runner import evaluate, main, selected_cases
from common.runs.tracks import Track, matches_track


class MigrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.cases = read_jsonl(DEFAULT_DATASET / "generated/golden.jsonl")
        cls.corpus = {row["id"]: row for row in read_json(DEFAULT_DATASET / "generated/corpus.json")}

    def test_all_archived_and_original_payload_hashes_match_before_move(self) -> None:
        report = read_json(DEFAULT_DATASET / "migration_preservation.json")
        self.assertGreaterEqual(report["preserved_file_count"], 140)
        for row in report["files"]:
            self.assertEqual(digest(EVALUATION_ROOT.parent / row["current_path"]), row["sha256"], row["current_path"])

    def test_exported_model_input_hashes_match_pre_migration_inputs(self) -> None:
        previous = read_json(DEFAULT_DATASET / "migration_preservation.json")["previous_input_hash_examples"]
        self.assertTrue(previous)
        inputs = {row["case_id"]: row["input_sha256"] for row in export_inputs(self.cases, self.corpus)}
        for case_id, value in previous.items():
            self.assertEqual(inputs[case_id], value)

    def test_track_views_retain_case_counts_and_shared_split(self) -> None:
        expected = {Track.SEARCH: 85, Track.TOOL_CALL: 200, Track.PLAN: 50, Track.STATE: 70, Track.MEMORY: 20, Track.BEHAVIOR: 45, Track.PERSONA: 200, Track.END_TO_END: 200}
        for track, count in expected.items():
            selected = [case for case in self.cases if matches_track(case, track)]
            self.assertEqual(len(selected), count)
            if track != Track.END_TO_END:
                view = read_jsonl(DEFAULT_DATASET / "generated/by_track" / f"{track.value}.jsonl")
                self.assertEqual(selected, view)
        persona = selected_cases(DEFAULT_DATASET, None, "all", ["TEXT"], ["persona"])
        self.assertEqual(len(persona), 47)

    def test_new_run_directories_never_overwrite_or_enter_dataset(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "run"
            allocate_run(Track.SEARCH, DEFAULT_DATASET, output)
            with self.assertRaises(FileExistsError):
                allocate_run(Track.SEARCH, DEFAULT_DATASET, output)
            with self.assertRaisesRegex(ValueError, "outside"):
                allocate_run(Track.SEARCH, DEFAULT_DATASET, DEFAULT_DATASET / "results")
            with self.assertRaisesRegex(ValueError, "outside"):
                allocate_run(Track.SEARCH, DEFAULT_DATASET, DEFAULT_DATASET.parent / "v1.3.0/results")

    def test_build_preserves_source_rubrics_and_sibling_runs(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            dataset = root / "datasets/v1.4.0"
            shutil.copytree(DEFAULT_DATASET, dataset)
            fixed = {path: digest(path) for folder in ("source", "rubrics") for path in (dataset / folder).rglob("*") if path.is_file()}
            marker = root / "runs/search/v1.4.0/previous/scores/results.jsonl"
            marker.parent.mkdir(parents=True)
            marker.write_text("existing real output")
            build(dataset)
            self.assertEqual(marker.read_text(), "existing real output")
            self.assertTrue(all(digest(path) == value for path, value in fixed.items()))

    def test_search_only_scores_rankings_without_judge_or_tool_penalties(self) -> None:
        case = next(case for case in self.cases if case["case_id"] == "PLR-TM-palaces-01")
        exported = export_inputs([case], self.corpus)[0]
        record = {"case_id": case["case_id"], "input_sha256": exported["input_sha256"], "response": copy.deepcopy(case["reference_envelope"]), "tool_calls": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = root / "responses.jsonl"
            output = root / "run"
            write_jsonl(responses, [record])
            with patch("common.runs.runner.score_message") as judge:
                code = asyncio.run(evaluate(root=DEFAULT_DATASET, group=None, cases=[case], responses_path=responses, output=output, use_judge=False, settings=JudgeSettings("gpt-4.1-mini", ""), track=Track.SEARCH))
                judge.assert_not_called()
            self.assertEqual(code, 0)
            result = read_jsonl(output / "scores/results.jsonl")[0]
            self.assertEqual(result["code"]["metrics"]["top_1_accuracy"], 1)
            self.assertNotIn("tool_name_and_hard_args_accuracy", result["code"]["metrics"])
            self.assertEqual(read_jsonl(output / "outputs/records.jsonl"), [record])
            with self.assertRaises(FileExistsError):
                asyncio.run(evaluate(root=DEFAULT_DATASET, group=None, cases=[case], responses_path=responses, output=output, use_judge=False, settings=JudgeSettings("gpt-4.1-mini", "")))

    def test_run_metadata_and_latest_do_not_mutate_prior_results(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            output = root / "chosen-run"
            run_id, _ = allocate_run(Track.TOOL_CALL, DEFAULT_DATASET, output)
            write_run_record(run_id=run_id, track=Track.TOOL_CALL, dataset=DEFAULT_DATASET, output=output, scope={"split": "test"}, status="completed")
            metadata = read_json(output / "run.json")
            self.assertEqual(metadata["dataset_manifest_sha256"], digest(DEFAULT_DATASET / "manifest.json"))
            self.assertEqual(metadata["scope"]["split"], "test")
            self.assertEqual(metadata["latency_measurement"], "not_collected_by_this_runner")
            with patch("common.runs.run_record.RUNS_ROOT", root / "runs"):
                update_latest(Track.TOOL_CALL, DEFAULT_DATASET, run_id, output)
            latest = read_json(root / "runs/tool_call/v1.4.0/latest.json")
            self.assertEqual(latest["run_id"], run_id)
            self.assertEqual(read_json(output / "run.json"), metadata)

    def test_track_cli_exports_from_arbitrary_working_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "inputs.jsonl"
            result = subprocess.run([sys.executable, str(EVALUATION_ROOT / "tracks/search/run.py"), "export-inputs", "--split", "development", "--output", str(target)], cwd=directory, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            rows = read_jsonl(target)
            self.assertTrue(rows)
            self.assertTrue(all("reference" not in row["model_input"] for row in rows))
            again = subprocess.run([sys.executable, str(EVALUATION_ROOT / "tracks/search/run.py"), "export-inputs", "--split", "development", "--output", str(target)], cwd=directory, capture_output=True, text=True)
            self.assertNotEqual(again.returncode, 0)
            self.assertIn("overwrite", again.stderr)

    def test_evaluate_command_writes_complete_run_and_precheck_keeps_latest(self) -> None:
        case = next(case for case in self.cases if case["case_id"] == "PLR-TM-palaces-01")
        exported = export_inputs([case], self.corpus)[0]
        record = {"case_id": case["case_id"], "input_sha256": exported["input_sha256"], "response": copy.deepcopy(case["reference_envelope"]), "tool_calls": []}
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            responses = root / "synthetic-command-test.jsonl"
            write_jsonl(responses, [record])
            arguments = ["run.py", "evaluate", "--split", "development", "--responses", str(responses)]
            with patch("common.runs.run_record.RUNS_ROOT", root / "runs"), patch.object(sys, "argv", arguments):
                with self.assertRaises(SystemExit) as exit_status:
                    main("search")
            self.assertEqual(exit_status.exception.code, 1)  # Coverage is intentionally partial.
            latest_path = root / "runs/search/v1.4.0/latest.json"
            latest = read_json(latest_path)
            output = Path(latest["path"])
            self.assertEqual(read_json(output / "run.json")["status"], "partial")
            self.assertTrue((output / "scores/results.jsonl").exists())
            self.assertEqual(read_jsonl(output / "outputs/records.jsonl"), [record])
            with patch("common.runs.run_record.RUNS_ROOT", root / "runs"), patch.object(sys, "argv", [*arguments, "--precheck-only"]):
                with self.assertRaises(SystemExit) as exit_status:
                    main("search")
            self.assertEqual(exit_status.exception.code, 0)
            self.assertEqual(read_json(latest_path), latest)


if __name__ == "__main__":
    unittest.main()
