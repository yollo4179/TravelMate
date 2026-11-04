from __future__ import annotations
import sys
from pathlib import Path
import tempfile
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from common.dataset.io import read_json
from common.execution.control import ExecutionSettings
from common.experiments.source_identity import source_identity
from tracks.conversation.log_types import EvaluationStage, TestLogPath
from tracks.conversation.test_logs import TestLogs
from tracks.conversation.cases import DEFAULT_SUITE
from tracks.conversation.run import prepared_cases
from argparse import Namespace

ROOT=Path(__file__).resolve().parents[1]

class RegistryTests(unittest.TestCase):
    def test_every_log_enum_has_one_function_and_unique_relative_path(self):
        self.assertEqual(len(TestLogs.ENTRIES),len(TestLogPath))
        self.assertEqual(set(TestLogs.WRITERS),set(TestLogPath))
        self.assertTrue(all(callable(writer) for writer in TestLogs.WRITERS.values()))
        self.assertTrue(all(not Path(key.value).is_absolute() and '..' not in Path(key.value).parts for key in TestLogPath))
        with tempfile.TemporaryDirectory() as directory:
            TestLogs.write(Path(directory),TestLogPath.RUN,{'status':'offline'})
            self.assertEqual(read_json(Path(directory)/TestLogPath.RUN.value),{'status':'offline'})

    def test_four_separate_units_cover_each_case_once_in_required_order(self):
        folder=ROOT/'experiments/conversation-smoke'
        stages=read_json(folder/'stage-order.json')['stages']
        self.assertEqual([item['stage'] for item in stages],[stage.value for stage in EvaluationStage])
        selected=[]
        for stage in stages:
            settings=ExecutionSettings.load(folder/stage['configuration'])
            cases=prepared_cases(Namespace(suite=DEFAULT_SUITE,bindings=folder/'offline-bindings.json'),settings)
            self.assertTrue(all(case['evaluation_stage']==stage['stage'] for case in cases))
            selected.extend(case['case_id'] for case in cases)
        self.assertEqual(len(selected),len(set(selected)))
        self.assertEqual(set(selected),{case['case_id'] for case in read_json(DEFAULT_SUITE)['cases']})

    def test_source_identity_changes_with_runtime_source_not_log_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'Example.java').write_text('v1')
            first=source_identity(root);(root/'Example.java').write_text('v2')
            self.assertNotEqual(first,source_identity(root))
