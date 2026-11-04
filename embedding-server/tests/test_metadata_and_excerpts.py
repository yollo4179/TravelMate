from __future__ import annotations
import sys
from pathlib import Path
import unittest
from unittest.mock import AsyncMock
sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parent)]
from app.contextual.metadata_filter import PlaceMetadataFilter
from app.contextual.excerpts import ReviewedExcerptModule, ExcerptInput, ChunkAspect, RelationCertainty
from app.contextual.contracts import SourceDocument, MAX_ACTIVE_CHUNKS
from app.contextual.pipeline import select_active
from test_contextual_general_search_contract import runtime_for, request_for
from contextual_search_fixtures import candidate, document


class MetadataOrderTests(unittest.IsolatedAsyncioTestCase):
    async def test_metadata_precedes_query_embedding_and_vector_reranking(self) -> None:
        runtime, reranker = runtime_for([candidate(901, [document('야경을 볼 수 있다.', relation=False)], [.9])], [.9])
        order = []
        original = runtime._retrieve_candidates.return_value
        async def eligible(payload): order.append('metadata'); return [901]
        async def retrieve(payload, vector): order.append('vector'); self.assertEqual(payload['eligible_place_ids'], [901]); return original
        runtime._eligible_place_ids = AsyncMock(side_effect=eligible)
        runtime._retrieve_candidates = AsyncMock(side_effect=retrieve)
        runtime._complete_recommendation.__func__.__globals__['embedder'].embed.side_effect = lambda _: (order.append('embedding') or [[1.] + [0.] * 1023])
        reranker.rerank.side_effect = lambda *args: (order.append('rerank') or [.9])
        await runtime._complete_recommendation(request_for('야경', filters={'region': '서울'}))
        self.assertEqual(order, ['metadata', 'embedding', 'vector', 'rerank'])

    async def test_empty_eligibility_skips_both_models_and_vector_lookup(self) -> None:
        runtime, reranker = runtime_for([], [])
        await runtime._complete_recommendation(request_for('주변', filters={'exclude_place_ids': [901]}))
        runtime._retrieve_candidates.assert_not_called()
        reranker.rerank.assert_not_called()
        runtime._complete_recommendation.__func__.__globals__['embedder'].embed.assert_not_called()
        self.assertEqual(runtime._save_recommendation_result.await_args.args[1]['items'], [])

    def test_filter_placeholders_are_parameterized_and_offset_safe(self) -> None:
        result = PlaceMetadataFilter.build({'region': "서울' OR true", 'city': '종로', 'exclude_place_ids': [12]}, offset=1)
        self.assertNotIn("서울", ' '.join(result.conditions))
        self.assertEqual(result.parameters, ("서울' OR true", '종로', [12]))
        self.assertIn('city = $3', result.conditions)


class ExcerptAdmissionTests(unittest.TestCase):
    def source(self, text='주차장이 있다.\n방문하며 산책을 즐겼다.'):
        return SourceDocument.from_mapping({'source_type': 'blog_post', 'title': '보존 원문', 'text': text,
            'metadata': {'source_url': 'https://example.org/original', 'capture_scope': 'full_text'}})

    def test_facets_use_separate_exact_original_spans_and_stable_ids(self) -> None:
        source = self.source()
        inputs = [ExcerptInput('주차장이 있다.', 1, ChunkAspect.PARKING, '주차 정보'), ExcerptInput('방문하며 산책을 즐겼다.', 1, ChunkAspect.EXPERIENCE, '체험 정보')]
        result = ReviewedExcerptModule().execute(source, inputs)
        self.assertEqual(len({c.chunk_id for c in result.chunks}), 2)
        self.assertEqual([c.generation['aspect'] for c in result.chunks], ['parking', 'experience'])
        self.assertTrue(all(c.chunk_text in source.text and c.source.source_id == source.source_id for c in result.chunks))
        self.assertEqual([c.chunk_id for c in result.chunks], [c.chunk_id for c in ReviewedExcerptModule().execute(source, inputs).chunks])

    def test_ambiguous_relation_is_held_without_destroying_the_original(self) -> None:
        source = self.source('다른 공원과 이어져 있을지도 모른다.')
        relation = {'type': 'movement'}
        result = ReviewedExcerptModule().execute(source, [ExcerptInput(source.text, 1, ChunkAspect.DESCRIPTION, '연결 여부는 확인되지 않은 원문', (relation,), RelationCertainty.AMBIGUOUS)])
        self.assertEqual(result.held_relations, (relation,))
        self.assertEqual(result.chunks, ())
        self.assertEqual(result.held_excerpts[0]['quote'], source.text)
        self.assertEqual(source.text, '다른 공원과 이어져 있을지도 모른다.')

    def test_nonexistent_or_duplicate_excerpt_is_rejected(self) -> None:
        for source, quote in [(self.source(), '무료 주차'), (self.source('주차. 주차.'), '주차.')]:
            with self.assertRaises(ValueError): ReviewedExcerptModule().execute(source, [ExcerptInput(quote, 1, ChunkAspect.PARKING, '설명')])

    def test_source_shortage_does_not_create_fifteen_fake_chunks(self) -> None:
        chunk, = ReviewedExcerptModule().execute(self.source(), [ExcerptInput('주차장이 있다.', 1, ChunkAspect.PARKING, '주차 정보')]).chunks
        self.assertEqual(MAX_ACTIVE_CHUNKS, 20)
        self.assertEqual(len(select_active(1, [chunk] * 30)), 1)
