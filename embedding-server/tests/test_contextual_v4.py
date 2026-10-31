"""v4 비교가 저장 요청·스키마·검증 규칙을 바꾸지 않는지 검증한다."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT.parent))
from app.contextual.artifacts import collect_bundle, load_record
from app.contextual.agent import parse_chunks
from app.contextual.profiles import ExecutionProfileId
from app.contextual.prompts import DEFAULT_PROMPT_VERSION, PromptVersion, resolve_prompt
from app.contextual.replay import GenerationBaseline
from app.contextual.validation import ValidationVersion
from test_contextual_profiles import legacy_archive
from Evaluation.tracks.contextual.prompt_comparison import read_api_key


class ContextualV4Tests(unittest.IsolatedAsyncioTestCase):
    def test_new_prompt_is_opt_in_and_uses_the_existing_validation_contract(self) -> None:
        self.assertEqual(DEFAULT_PROMPT_VERSION, PromptVersion.V2)
        prompt = resolve_prompt(PromptVersion.V4)
        self.assertTrue(prompt.require_empty_unattributed_entities)
        self.assertFalse(prompt.allow_hypothetical_questions)
        self.assertNotEqual(prompt.instructions, resolve_prompt(PromptVersion.V2).instructions)

    async def test_v2_to_v4_keeps_exact_input_model_effort_limit_and_schema(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            original = legacy_archive(root / 'original')
            first = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            response = json.loads(original.with_name('raw_response.json').read_text())
            async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: httpx.Response(200, json=response))) as client:
                v2 = await collect_bundle(first.bundle, first.settings('test-only', 30), root / 'v2', client,
                    prompt_version=PromptVersion.V2, prepared_request=first.candidate_request(PromptVersion.V2),
                    request_profile_id=first.request_profile_id)
            baseline = GenerationBaseline.load(v2)
            before = {path: path.read_bytes() for path in v2.parent.iterdir() if path.is_file()}
            payload = baseline.candidate_request(PromptVersion.V4)
            changed = [key for key in payload if payload[key] != baseline.request[key]]
            self.assertEqual(changed, ['instructions'])
            self.assertEqual(payload['model'], 'perplexity/sonar')
            self.assertEqual(payload['effort'], 'fast')
            self.assertEqual(payload['max_output_tokens'], 8192)
            self.assertEqual(payload['tools'], [])

            def handler(request: httpx.Request) -> httpx.Response:
                self.assertEqual(json.loads(request.content), payload)
                return httpx.Response(200, json=response)

            async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
                v4 = await collect_bundle(baseline.bundle, baseline.settings('test-only', 30), root / 'v4', client,
                    prompt_version=PromptVersion.V4, prepared_request=payload, request_profile_id=baseline.request_profile_id)
            _, chunks, record = load_record(v4)
            self.assertTrue(chunks)
            self.assertEqual(record['validation_version'], ValidationVersion.SUBJECT_ONLY)
            compact_report = baseline.write_report(v4, output_directory=root / 'reports')
            self.assertEqual(compact_report.parent, root / 'reports')
            comparison = json.loads(compact_report.read_text())
            self.assertTrue(comparison['actual_model_match'])
            self.assertTrue(comparison['validation_versions_match'])
            self.assertEqual(before, {path: path.read_bytes() for path in before})
            modified = {**payload, 'max_output_tokens': 4096}
            with self.assertRaises(ValueError):
                baseline.verify_request(modified)

    def test_v4_keeps_mentioned_only_and_empty_attribution_valid_without_forced_subject(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            original = legacy_archive(Path(directory))
            baseline = GenerationBaseline.load(original, profile_id=ExecutionProfileId.V1_LOCAL)
            original_raw = json.loads(original.with_name('raw_response.json').read_text())
            for mentioned in (True, False):
                raw = deepcopy(original_raw)
                document = json.loads(raw['output'][0]['content'][0]['text'])
                chunk = document['chunks'][0]
                if mentioned:
                    chunk['place_refs'][0]['role'] = 'mentioned'
                    chunk['entities'][0]['role'] = 'mentioned'
                else:
                    chunk['place_refs'] = []
                    chunk['entities'] = []
                raw['output'][0]['content'][0]['text'] = json.dumps(document)
                self.assertEqual(parse_chunks(raw, baseline.bundle.places, baseline.bundle.sources,
                    prompt_version=PromptVersion.V4, validation_version=ValidationVersion.SUBJECT_ONLY), [])

    def test_explicit_key_file_must_identify_one_key(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'key.txt'
            key = 'pplx-' + 'a' * 30
            path.write_text('API key: ' + key, encoding='utf-8')
            self.assertEqual(read_api_key(path), key)
            path.write_text('키 값 없음', encoding='utf-8')
            with self.assertRaises(ValueError):
                read_api_key(path)


if __name__ == '__main__':
    unittest.main()
