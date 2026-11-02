"""Offline safety regressions; these are not B-plan quality evaluation cases."""
from __future__ import annotations

import asyncio
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import prepare
import run_b


class PreparationTests(unittest.TestCase):
    def test_source_databases_never_accept_writes(self) -> None:
        for source in (prepare.SOURCE_SPRING, prepare.SOURCE_SEARCH):
            with self.subTest(source=source.container), self.assertRaises(ValueError):
                asyncio.run(prepare.sql(source, "DELETE FROM places;", write=True))

    def test_unknown_target_cannot_accept_writes(self) -> None:
        target = prepare.DatabaseTarget("other", "b_eval", "travelmate_b_spring")
        with self.assertRaises(ValueError):
            asyncio.run(prepare.sql(target, "SELECT 1;", write=True))

    def test_snapshot_queries_are_explicitly_read_only(self) -> None:
        async def capture(*arguments: str, stdin: str | None = None) -> str:
            self.assertTrue(stdin.startswith("BEGIN READ ONLY;"))
            self.assertIn("SET LOCAL TIME ZONE 'Asia/Seoul'", stdin)
            return "[]"
        with patch.object(prepare, "command", capture):
            self.assertEqual([], asyncio.run(prepare.rows(prepare.SOURCE_SPRING, "places", "id")))

    def test_import_identifiers_are_allowlisted_and_literals_escaped(self) -> None:
        with self.assertRaises(ValueError):
            prepare.insert_records("users; DROP TABLE places", [])
        statement = prepare.insert_records("places", [{"description": "a'b\\c"}], identity=True)
        self.assertIn("a''b", statement)
        self.assertIn("OVERRIDING SYSTEM VALUE", statement)

    def test_invalid_preserved_vectors_never_trigger_generation(self) -> None:
        for vector in ([1.0], [float("nan")] * 1024, [float("inf")] * 1024):
            with self.subTest(length=len(vector)), self.assertRaises(ValueError):
                prepare.vector_text(vector)

    def test_configuration_refuses_to_overwrite_existing_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(ValueError):
                prepare.configure(Path(directory), Path("not-used"))

    def test_places_with_matching_ids_but_different_descriptions_have_different_fingerprints(self) -> None:
        original = {"id": 311, "name": "park", "description": "Entry is restricted."}
        changed = {**original, "description": "Entry is permitted."}
        self.assertNotEqual(prepare.ExistingPlace.from_mapping(original).source_fingerprint,
                            prepare.ExistingPlace.from_mapping(changed).source_fingerprint)

    def test_execute_flag_still_blocks_before_network_when_evidence_is_missing(self) -> None:
        with patch.object(sys, "argv", ["run_b.py", "--runtime", ".", "--execute"]), \
                patch.object(run_b, "execution_blockers", return_value=["missing_preserved_evidence"]), \
                patch.object(run_b, "execute") as live_execution:
            with self.assertRaises(SystemExit):
                asyncio.run(run_b.main())
            live_execution.assert_not_called()

    def test_default_inspection_never_dispatches_even_if_prerequisites_pass(self) -> None:
        with patch.object(sys, "argv", ["run_b.py", "--runtime", "."]), \
                patch.object(run_b, "execution_blockers", return_value=[]), \
                patch.object(run_b, "execute") as live_execution:
            asyncio.run(run_b.main())
            live_execution.assert_not_called()

    def test_live_collector_rejects_repeated_tools_and_missing_call_observations(self) -> None:
        response = {"termination": "COMPLETED", "type": "PLACES",
                    "toolResults": [{"name": "search_places", "status": "SUCCEEDED"}]}
        for calls in ([], [{"name": "search_places"}] * 2):
            events = [{"event": "MODEL_TURN", "payload": {"toolCalls": calls}}]
            with self.subTest(calls=len(calls)), self.assertRaises(ValueError):
                run_b.validate_completed_turn(response, events)
        events = [{"event": "MODEL_TURN", "payload": {"toolCalls": [{"name": "search_places"}]}}]
        with self.assertRaises(ValueError):
            run_b.validate_completed_turn(response, events)


if __name__ == "__main__":
    unittest.main()
