from __future__ import annotations
import json
import subprocess
import sys
import tempfile
from pathlib import Path
import unittest
sys.path[:0] = [str(Path(__file__).resolve().parents[1])]
from app.contextual.contracts import ContentKind, MAX_ACTIVE_CHUNKS, MIN_TARGET_ACTIVE_CHUNKS, SearchChunk, SourceDocument, PlaceRole
from app.contextual.excerpts import (ChunkAspect, ExcerptConfig, ExcerptHoldReason, ExcerptInput, ExcerptIntake,
                                     ReviewedExcerptModule)
from app.contextual.repository import summarize_coverage
from app.contextual.selection import ActiveSelectionVersion, chunk_aspect, select_active


def source(text: str, url: str = 'https://example.org/original') -> SourceDocument:
    return SourceDocument.from_mapping({'source_type': 'blog_post', 'title': '보존 원문', 'text': text,
                                        'metadata': {'source_url': url, 'capture_scope': 'full_text'}})


def excerpt_chunk(index: int, aspect: ChunkAspect) -> SearchChunk:
    text = f'{aspect.label} 관련 관찰 {index}번 문장이다.'
    chunk, = ReviewedExcerptModule().execute(source(text, f'https://example.org/{aspect.value}/{index}'),
                                             [ExcerptInput(text, 1, aspect, '검수한 인용', reviewer='reviewer')]).chunks
    return chunk


def unclassified_chunk(index: int) -> SearchChunk:
    document = source(f'생성 문맥이 붙은 원문 {index}', f'https://example.org/generated/{index}')
    return SearchChunk(document, 0, len(document.text), '생성 문맥', [{'place_id': 1, 'role': PlaceRole.SUBJECT}],
                       {'provider': 'perplexity', 'model': None, 'prompt_version': 'test'})


class ExcerptAspectTests(unittest.TestCase):
    def test_aspect_label_is_embedded_and_content_kind_is_an_enum_value(self) -> None:
        chunk = excerpt_chunk(1, ChunkAspect.PARKING)
        self.assertTrue(chunk.context_text.startswith('[주차] '))
        self.assertIn('[주차]', chunk.embedding_text)
        self.assertEqual(chunk.content_kind, ContentKind.OTHER.value)
        self.assertEqual(chunk_aspect(chunk), ChunkAspect.PARKING)
        self.assertIsNone(chunk_aspect(unclassified_chunk(1)))

    def test_quote_longer_than_two_or_three_lines_is_held_for_the_reviewer(self) -> None:
        long_text = '가' * 201
        result = ReviewedExcerptModule().execute(source(long_text), [ExcerptInput(long_text, 1, ChunkAspect.REVIEW, '후기')])
        self.assertEqual(result.chunks, ())
        self.assertEqual(result.held_excerpts[0]['reason'], ExcerptHoldReason.QUOTE_TOO_LONG.value)
        relaxed = ReviewedExcerptModule().execute(source(long_text), [ExcerptInput(long_text, 1, ChunkAspect.REVIEW, '후기')],
                                                  ExcerptConfig(max_quote_characters=300))
        self.assertEqual(len(relaxed.chunks), 1)

    def test_intake_file_selects_the_registered_module(self) -> None:
        document = {'version': 'reviewed-excerpts-v1',
                    'source': {'source_type': 'review', 'title': '후기', 'text': '주차장이 넓다. 산책이 좋았다.',
                               'metadata': {'source_url': 'https://example.org/r', 'capture_scope': 'full_text'}},
                    'excerpts': [{'quote': '주차장이 넓다.', 'subject_place_id': 7, 'aspect': 'parking', 'context': '주차', 'reviewer': 'r'},
                                 {'quote': '산책이 좋았다.', 'subject_place_id': 7, 'aspect': 'experience', 'context': '체험'}]}
        result = ExcerptIntake.from_mapping(document).execute()
        self.assertEqual([chunk_aspect(chunk) for chunk in result.chunks], [ChunkAspect.PARKING, ChunkAspect.EXPERIENCE])
        with self.assertRaises(ValueError):
            ExcerptIntake.from_mapping({**document, 'version': 'unknown'})


class ActiveSelectionTests(unittest.TestCase):
    def chunks(self) -> list[SearchChunk]:
        parking = [excerpt_chunk(index, ChunkAspect.PARKING) for index in range(25)]
        return parking + [excerpt_chunk(0, ChunkAspect.DESCRIPTION), excerpt_chunk(0, ChunkAspect.REVIEW), unclassified_chunk(0)]

    def test_default_keeps_source_round_robin(self) -> None:
        chunks = self.chunks()
        self.assertEqual(select_active(1, chunks), select_active(1, chunks, ActiveSelectionVersion.SOURCE_ROUND_ROBIN_V1))
        self.assertTrue(all(chunk_aspect(chunk) == ChunkAspect.PARKING for chunk in select_active(1, chunks)))

    def test_aspect_round_robin_keeps_every_available_aspect(self) -> None:
        selected = select_active(1, self.chunks(), ActiveSelectionVersion.ASPECT_ROUND_ROBIN_V2)
        self.assertEqual(len(selected), MAX_ACTIVE_CHUNKS)
        self.assertEqual({chunk_aspect(chunk) for chunk in selected},
                         {ChunkAspect.PARKING, ChunkAspect.DESCRIPTION, ChunkAspect.REVIEW, None})
        self.assertEqual(len({chunk.chunk_id for chunk in selected}), len(selected))

    def test_unknown_selection_version_fails_explicitly(self) -> None:
        with self.assertRaises(ValueError):
            select_active(1, self.chunks(), 'invented-v9')


class CoverageTests(unittest.TestCase):
    def test_places_below_fifteen_are_listed_without_filling(self) -> None:
        report = summarize_coverage([{'place_id': 1, 'name': 'A', 'active_chunks': 3},
                                     {'place_id': 2, 'name': 'B', 'active_chunks': MIN_TARGET_ACTIVE_CHUNKS},
                                     {'place_id': 3, 'name': 'C', 'active_chunks': 20}])
        self.assertEqual(report['target'], {'min': 15, 'max': 20})
        self.assertEqual([row['place_id'] for row in report['below_target']], [1])
        self.assertEqual(report['within_target'], 2)


class ExcerptCliTests(unittest.TestCase):
    def test_dry_run_writes_chunks_and_holds_without_a_database(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            intake = Path(folder) / 'intake.json'
            intake.write_text(json.dumps({'version': 'reviewed-excerpts-v1',
                'source': {'source_type': 'blog_post', 'title': '원문', 'text': '주차가 편하다. ' + '나' * 230,
                           'metadata': {'source_url': 'https://example.org/b', 'capture_scope': 'full_text'}},
                'excerpts': [{'quote': '주차가 편하다.', 'subject_place_id': 3, 'aspect': 'parking', 'context': '주차'},
                             {'quote': '나' * 230, 'subject_place_id': 3, 'aspect': 'review_impression', 'context': '후기'}]},
                ensure_ascii=False), encoding='utf-8')
            output = Path(folder) / 'out' / 'result.json'
            completed = subprocess.run([sys.executable, '-m', 'app.contextual.cli', 'excerpts', '--input', str(intake), '--output', str(output)],
                                       cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, encoding='utf-8')
            self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)
            result = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(len(result['chunks']), 1)
            self.assertEqual(result['held_excerpts'][0]['reason'], ExcerptHoldReason.QUOTE_TOO_LONG.value)
            self.assertEqual(json.loads(completed.stdout.strip().splitlines()[-1])['status'], 'NOT_APPLIED')


if __name__ == '__main__':
    unittest.main()
