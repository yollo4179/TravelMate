"""Regression tests for dataset labels, provenance, leakage and reproducibility."""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('dataset_builder', ROOT / 'build_dataset.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class DatasetTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.snapshot = builder.read_json(ROOT / 'snapshot.json')
        cls.cases = [json.loads(line) for line in (ROOT / 'golden.jsonl').read_text().splitlines()]
        cls.index = {case['case_id']: case for case in cls.cases}

    def reject(self, mutate: Callable[[list[dict[str, Any]]], None], message: str) -> None:
        altered = copy.deepcopy(self.cases)
        mutate(altered)
        with self.assertRaisesRegex(ValueError, message):
            builder.validate_cases(altered, self.snapshot, 100)

    def test_full_dataset_check_does_not_modify_inputs(self) -> None:
        before = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in ROOT.iterdir() if path.is_file()}
        result = builder.check(ROOT)
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(result['case_count'], 100)
        self.assertEqual(result['counts_by_evaluation_track'], {'search_api': 60, 'context_search': 20, 'answer_behavior': 20})
        after = {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in ROOT.iterdir() if path.is_file()}
        self.assertEqual(before, after)
        self.assertTrue(result['human_review_completed'])
        self.assertEqual(result['reference_count'], 100)
        self.assertEqual(result['missing_reference_count'], 0)
        self.assertEqual(result['answerable_missing_reference_count'], 0)

    def test_reference_contexts_exclude_distractors_and_preserve_real_runtime_boundary(self) -> None:
        case = self.index['TM-palaces-01']
        self.assertEqual(case['reference'], '찾으신 장소는 창경궁입니다.')
        self.assertEqual(case['reference_context_ids'], [378])
        self.assertTrue(any('창경궁' in context for context in case['reference_contexts']))
        self.assertNotIn('retrieved_contexts', case)
        self.assertEqual(case['reference_provenance']['author'], 'Codex')
        self.assertEqual(case['review']['human_reviewer'], 'user')
        self.reject(
            lambda cases: cases[0]['reference_contexts'].append('원문에 없는 근거'),
            'reference contexts differ',
        )
        self.reject(
            lambda cases: cases[0]['reference_context_ids'].append(208),
            'reference contexts differ',
        )

    def test_behavior_references_are_actual_refusal_or_clarification_answers(self) -> None:
        refusal = self.index['TM-palaces-05']
        self.assertIn('확인할 수 없습니다', refusal['reference'])
        clarification = self.index['TM-churches-05']
        self.assertIn('어느 성당', clarification['reference'])
        self.assertEqual(clarification['reference_contexts'], [])
        self.assertEqual(clarification['reference_context_ids'], [])
        self.assertEqual(self.index['TM-aquariums-05']['reference_contexts'], [])

    def test_review_completion_is_authored_and_requires_attribution(self) -> None:
        authored = builder.read_json(ROOT / 'cases.source.json')
        for group in authored['groups']:
            for case in group['cases']:
                self.assertEqual(case['review']['status'], 'human_reviewed')
                self.assertTrue(case['review']['human_reviewer'])
                self.assertTrue(case['review']['human_reviewed_at'])
        self.reject(
            lambda cases: cases[0]['review'].__setitem__('human_reviewer', None),
            'reviewed label requires reviewer and date',
        )
        self.reject(
            lambda cases: cases[0]['review'].__setitem__('human_reviewed_at', None),
            'reviewed label requires reviewer and date',
        )

    def test_unauthored_review_remains_pending(self) -> None:
        authored = copy.deepcopy(builder.read_json(ROOT / 'cases.source.json'))
        for group in authored['groups']:
            for case in group['cases']:
                case.pop('review', None)
        cases = builder.assemble_cases(
            self.snapshot,
            authored,
            self.cases[0]['snapshot_id'],
        )
        result = builder.validate_cases(cases, self.snapshot, 100)
        self.assertFalse(result['human_review_completed'])
        self.assertTrue(all(case['review']['status'] == 'pending_human_review' for case in cases))

    def test_original_snapshot_bytes_are_preserved(self) -> None:
        self.assertEqual(builder.digest_file(ROOT / 'snapshot.json'), '410a9c3c46004cb30644455fe9d5ddb01a52a04a700ffe04159605cf94661218')
        self.assertEqual(len(self.snapshot['places']), 449)
        self.assertEqual(len(self.snapshot['tour_api_raw']), 449)

    def test_unsupported_hard_conditions_are_no_longer_answers(self) -> None:
        reviewed = {'TM-hanok_neighborhoods-02': 165, 'TM-aquariums-02': 109, 'TM-future_technology-02': 230, 'TM-safety_education-02': 278}
        for case_id, place_id in reviewed.items():
            with self.subTest(case_id=case_id):
                case = self.index[case_id]
                judgment = next(item for item in case['judgments'] if item['place_id'] == place_id)
                self.assertLess(judgment['relevance'], case['relevance_threshold'])
                self.assertNotIn(place_id, case['relevant_place_ids'])
                self.assertTrue(case['semantic_constraints'])

    def test_dj_box_question_has_direct_quoted_evidence(self) -> None:
        case = self.index['TM-food_streets-02']
        target = next(item for item in case['judgments'] if item['place_id'] == 254)
        self.assertTrue(any('떡볶이집마다 있었던 DJ박스' in item.get('quote', '') for item in target['evidence']))
        self.assertEqual(case['relevant_place_ids'], [254])

    def test_missing_hanok_answer_is_added_with_evidence(self) -> None:
        case = self.index['TM-hanok_neighborhoods-03']
        self.assertIn(64, case['relevant_place_ids'])
        target = next(item for item in case['judgments'] if item['place_id'] == 64)
        self.assertTrue(any('한옥' in item.get('quote', '') for item in target['evidence']))

    def test_unknown_and_zero_grade_relevant_ids_are_rejected(self) -> None:
        for invalid in [[999999], [208]]:
            with self.subTest(invalid=invalid):
                self.reject(lambda cases: cases[0].__setitem__('relevant_place_ids', invalid), 'relevant_place_ids')

    def test_stale_eligible_count_is_rejected(self) -> None:
        self.reject(lambda cases: cases[0]['condition_check'].__setitem__('eligible_place_count', 123456), 'stale corpus/eligible')

    def test_changed_provenance_is_rejected(self) -> None:
        for field, value in [('source_fetched_at', '2099-01-01'), ('tour_content_id', 'wrong'), ('snapshot_exported_at', 'wrong'), ('source_provider', 'wrong')]:
            with self.subTest(field=field):
                self.reject(lambda cases: cases[0]['judgments'][0]['evidence'][0].__setitem__(field, value), 'provenance')

    def test_incorrect_quote_offset_and_identity_are_rejected(self) -> None:
        self.reject(lambda cases: cases[0]['judgments'][0]['evidence'][1].__setitem__('char_end', 999999), 'invalid evidence span')
        self.reject(lambda cases: cases[0]['judgments'][0].__setitem__('name', 'wrong'), 'identity mismatch')

    def test_semantically_unsupported_candidate_cannot_be_promoted(self) -> None:
        def mutate(cases: list[dict[str, Any]]) -> None:
            case = next(item for item in cases if item['case_id'] == 'TM-hanok_neighborhoods-02')
            judgment = next(item for item in case['judgments'] if item['place_id'] == 165)
            judgment['relevance'] = 2
            case['relevant_place_ids'].append(165)
        self.reject(mutate, 'required semantic condition')

    def test_question_group_split_leakage_is_rejected(self) -> None:
        def mutate(cases: list[dict[str, Any]]) -> None:
            next(item for item in cases if item['case_id'] == 'TM-crafts-01')['split'] = 'development'
        self.reject(mutate, 'Question family split leakage')

    def test_same_place_may_be_judged_in_both_splits(self) -> None:
        splits = {case['split'] for case in self.cases if any(j['place_id'] == 222 for j in case['judgments'])}
        self.assertEqual(splits, {'development', 'test'})
        self.assertIn(222, self.index['TM-wetlands-03']['relevant_place_ids'])

    def test_v130_hard_conditions_require_evidence(self) -> None:
        expected = {
            'TM-crafts-03': ([55], [427, 415, 164]),
            'TM-gardens-03': ([222, 45], [412, 219]),
            'TM-wetlands-03': ([6, 289, 48, 222], [8]),
            'TM-literary_homes-03': ([336, 337, 349], [437]),
        }
        for case_id, (relevant, excluded) in expected.items():
            with self.subTest(case_id=case_id):
                case = self.index[case_id]
                self.assertEqual(case['relevant_place_ids'], relevant)
                self.assertTrue(case['semantic_constraints'])
                for place_id in excluded:
                    judgment = next(item for item in case['judgments'] if item['place_id'] == place_id)
                    self.assertEqual(judgment['relevance'], 1)
                    self.assertIn('not_supported', judgment['semantic_constraint_support'].values())

    def test_wrong_track_is_rejected(self) -> None:
        self.reject(lambda cases: cases[0].__setitem__('evaluation_track', 'context_search'), 'evaluation track mismatch')

    def test_radius_checks_inside_outside_and_exclusion(self) -> None:
        conditions = {'region': '서울', 'city': None, 'category': None, 'exclude_place_ids': [], 'area': {'center': {'latitude': 37.0, 'longitude': 127.0}, 'radius_meters': 500}}
        base = {'id': 1, 'region': '서울', 'city': '시험', 'category': '관광지', 'longitude': 127.0}
        self.assertTrue(builder.matches_conditions({**base, 'latitude': 37.003}, conditions))
        self.assertFalse(builder.matches_conditions({**base, 'latitude': 37.01}, conditions))
        conditions['exclude_place_ids'] = [1]
        self.assertFalse(builder.matches_conditions({**base, 'latitude': 37.0}, conditions))

    def test_source_and_derived_outputs_must_stay_in_sync(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source in ROOT.iterdir():
                if source.is_file():
                    shutil.copy2(source, target / source.name)
            authored = builder.read_json(target / 'cases.source.json')
            authored['groups'][0]['cases'][0]['query'] = '변경했지만 재생성하지 않은 질문'
            builder.write_json(target / 'cases.source.json', authored)
            manifest = builder.read_json(target / 'manifest.json')
            manifest['authoring_sha256'] = builder.digest_file(target / 'cases.source.json')
            builder.write_json(target / 'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'authoring source'):
                builder.check(target)

    def test_reference_survives_rebuild_in_every_matching_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for filename in ['snapshot.json', 'cases.source.json', 'build_dataset.py']:
                shutil.copy2(ROOT / filename, target / filename)
            authored = builder.read_json(target / 'cases.source.json')
            expected = {}
            for group in authored['groups']:
                for case in group['cases']:
                    case.pop('reference', None)
                    if case['case_suffix'] not in (1, 4, 5):
                        continue
                    case_id = f"TM-{group['group_id']}-{case['case_suffix']:02d}"
                    if case['judgments']:
                        place_id = case['judgments'][0]['place_id']
                        place = next(place for place in self.snapshot['places'] if place['id'] == place_id)
                        reference = f"{place['name']}을 찾으시면 됩니다.\n이는 회귀 테스트용 기대 답변입니다."
                    else:
                        reference = case['expected_action']
                    case['reference'] = reference
                    expected[case_id] = reference
            builder.write_json(target / 'cases.source.json', authored)
            builder.build(target)
            self.assertEqual(builder.check(target)['reference_count'], len(expected))
            for filename in ['golden.jsonl', 'development.jsonl', 'test.jsonl',
                             'search_api.jsonl', 'context_search.jsonl', 'answer_behavior.jsonl']:
                for line in (target / filename).read_text(encoding='utf-8').splitlines():
                    case = json.loads(line)
                    self.assertIn('reference', case)
                    self.assertEqual(case['reference'], expected.get(case['case_id']))

    def test_reference_source_edits_require_jsonl_regeneration(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for source in ROOT.iterdir():
                if source.is_file():
                    shutil.copy2(source, target / source.name)
            authored = builder.read_json(target / 'cases.source.json')
            authored['groups'][0]['cases'][0]['reference'] = '창경궁을 찾으시면 됩니다.'
            builder.write_json(target / 'cases.source.json', authored)
            manifest = builder.read_json(target / 'manifest.json')
            manifest['authoring_sha256'] = builder.digest_file(target / 'cases.source.json')
            builder.write_json(target / 'manifest.json', manifest)
            with self.assertRaisesRegex(ValueError, 'authoring source'):
                builder.check(target)
            builder.build(target)
            self.assertEqual(builder.check(target)['reference_count'], 100)
            rebuilt_case = json.loads((target / 'golden.jsonl').read_text().splitlines()[0])
            self.assertEqual(rebuilt_case['reference'], '창경궁을 찾으시면 됩니다.')

    def test_invalid_or_absent_reference_field_is_rejected(self) -> None:
        for invalid in ['', '  \n ', 3, False, [], {}]:
            with self.subTest(reference=invalid):
                self.reject(lambda cases: cases[0].__setitem__('reference', invalid), 'reference must be')
        self.reject(lambda cases: cases[0].pop('reference'), 'reference field missing; rebuild JSONL')

    def test_structure_pass_does_not_imply_references_are_ready(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for filename in ['snapshot.json', 'cases.source.json', 'build_dataset.py']:
                shutil.copy2(ROOT / filename, target / filename)
            authored = builder.read_json(target / 'cases.source.json')
            for group in authored['groups']:
                for case in group['cases']:
                    case.pop('reference', None)
            builder.write_json(target / 'cases.source.json', authored)
            builder.build(target)
            result = builder.check(target)
            self.assertEqual(result['reference_count'], 0)
            self.assertEqual(result['missing_reference_count'], 100)
            self.assertEqual(result['answerable_missing_reference_count'], 80)
            with self.assertRaisesRegex(ValueError, '80 answerable cases lack reference'):
                builder.check(target, require_reference=True)

    def test_reference_requirement_applies_to_answerable_cases(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for filename in ['snapshot.json', 'cases.source.json', 'build_dataset.py']:
                shutil.copy2(ROOT / filename, target / filename)
            authored = builder.read_json(target / 'cases.source.json')
            for group in authored['groups']:
                for case in group['cases']:
                    case['reference'] = None
                    if case['judgments']:
                        case['reference'] = '회귀 테스트용 기대 답변입니다.'
            builder.write_json(target / 'cases.source.json', authored)
            builder.build(target)
            result = builder.check(target, require_reference=True)
            self.assertEqual(result['answerable_missing_reference_count'], 0)
            self.assertEqual(result['missing_reference_count'], 20)
            self.assertTrue(result['human_review_completed'])

    def test_build_is_byte_reproducible_and_generated_lines_are_lf(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory)
            for filename in ['snapshot.json', 'cases.source.json', 'build_dataset.py']:
                shutil.copy2(ROOT / filename, target / filename)
            builder.build(target)
            first = {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()}
            builder.build(target)
            second = {path.name: path.read_bytes() for path in target.iterdir() if path.is_file()}
            self.assertEqual(first, second)
            for name, content in first.items():
                if name.endswith(('.json', '.jsonl')) and name != 'snapshot.json':
                    self.assertNotIn(b'\r\n', content)
            self.assertEqual(builder.check(target)['status'], 'passed')


if __name__ == '__main__':
    unittest.main()
