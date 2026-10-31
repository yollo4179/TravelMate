"""잘못된 근거 일치와 비교 누락이 성공 점수로 집계되지 않는지 검증한다."""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from Evaluation.tracks.contextual.score import aggregate, evidence_id, observations, score


class ScoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.row = {'id': 'P01-S01', 'pair_id': 'P01', 'source_id': 'one',
                    'source_version': 'version-a', 'start': 0, 'end': 10}
        self.evidence = {'source_id': 'one', 'source_version': 'version-a',
                         'source_span': {'start': 0, 'end': 10}}

    def test_same_source_other_span_is_not_a_gold_match(self) -> None:
        wrong = deepcopy(self.evidence)
        wrong['source_span'] = {'start': 10, 'end': 20}
        self.assertIsNone(evidence_id(wrong, [self.row], 'P01'))

    def test_changed_source_version_is_not_a_gold_match(self) -> None:
        wrong = {**self.evidence, 'source_version': 'version-b'}
        self.assertIsNone(evidence_id(wrong, [self.row], 'P01'))

    def test_same_source_in_another_pair_is_not_a_gold_match(self) -> None:
        self.assertIsNone(evidence_id(self.evidence, [self.row], 'P02'))
        self.assertEqual(evidence_id(self.evidence, [self.row], 'P01'), 'P01-S01')

    def test_correct_place_with_wrong_evidence_does_not_score_evidence_hit(self) -> None:
        summary = aggregate([{'target_semantic_rank_at_30': 1, 'target_rank_at_20': 1, 'gold_span_hit': False}])
        self.assertEqual(summary['target_top_1'], 1)
        self.assertEqual(summary['target_and_gold_span_at_5'], 0)

    def test_missing_counterpart_is_rejected_before_scoring(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cases = {'queries': [{'id': 'Q01'}]}
            (root / 'cases.json').write_text(json.dumps(cases), encoding='utf-8')
            run = {'status': 'COMPLETED', 'cases_sha256': hashlib.sha256((root / 'cases.json').read_bytes()).hexdigest(),
                   'completed': [{'query_id': 'Q01', 'version': 'v1'}]}
            for name, document in [('run.json', run), ('cleanup.json', {}), ('prepared.json', {})]:
                (root / name).write_text(json.dumps(document), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '비교 상대'):
                score(argparse.Namespace(cases=root / 'cases.json', prepared=root / 'prepared.json', results=root))

    def test_result_from_another_query_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            query = {'id': 'Q01', 'pair_id': 'P01', 'query': 'fixed query', 'kind': 'supported'}
            (root / 'Q01-v1.json').write_text(json.dumps({'query_id': 'Q02'}), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, '식별자'):
                observations(root, {'queries': [query]}, {'rows': []})

    def test_explicit_prompt_versions_do_not_relabel_v2_as_v1(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            query = {'id': 'Q01', 'pair_id': 'P01', 'query': 'fixed query', 'kind': 'supported', 'relevance': {}}
            for version in ('v2', 'v4'):
                result = {'query_id': query['id'], 'version': version, 'pair_id': query['pair_id'],
                          'query': query['query'], 'kind': query['kind'], 'semantic_candidates': [],
                          'result': {'status': 'COMPLETED', 'items': []}}
                (root / f'Q01-{version}.json').write_text(json.dumps(result), encoding='utf-8')
            rows = observations(root, {'target_place_id': 394, 'queries': [query]}, {'rows': []}, ('v2', 'v4'))
            self.assertEqual([row['version'] for row in rows], ['v2', 'v4'])


if __name__ == '__main__':
    unittest.main()
