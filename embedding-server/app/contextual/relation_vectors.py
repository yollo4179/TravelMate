"""활성 청크의 검증된 이동 인용만 별도 후보 검색 벡터로 표현한다."""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from .contracts import ContentKind, SearchChunk
from .observation_search import ObservationFilter
from .relations import independent_relations


class RelationRetrievalMode(StrEnum):
    CHUNK_ONLY = "chunk-only"
    CHUNK_AND_RELATION = "chunk-and-relation-v1"


class VectorRepresentation(StrEnum):
    RELATION_QUOTE = "relation-quote-vector-v1"


class RetrievalPath(StrEnum):
    CHUNK = "chunk"
    RELATION = "relation"
    ORIGINAL_FIELD = "original_field"


@dataclass(frozen=True)
class RelationVectorInput:
    chunk_id: str
    context_version: str
    relation_index: int
    evidence: dict[str, Any]

    @property
    def text(self) -> str:
        return self.evidence["quote"]


def relation_embedding_inputs(chunks: list[SearchChunk]) -> list[RelationVectorInput]:
    return [RelationVectorInput(chunk.chunk_id, chunk.context_version, index, deepcopy(relation["evidence"]))
            for chunk in chunks if independent_relations(chunk.relations)
            for index, relation in enumerate(chunk.relations)]


def relation_vector_sql(observation: ObservationFilter, parameters: list[Any]) -> tuple[str, str]:
    return _vector_sql(
        observation,
        parameters,
        chunk_condition="",
        selection="ORDER BY vectors.embedding <=> $1::vector, vectors.relation_index NULLS FIRST LIMIT 1",
    )


def semantic_relation_vector_sql(parameters: list[Any]) -> tuple[str, str]:
    # 도착지 슬롯에서는 출발지의 경관을 담은 전체 청크를 검색 표현으로 쓰지 않는다.
    return _vector_sql(
        ObservationFilter(content_kinds=(ContentKind.MOVEMENT,)),
        parameters,
        chunk_condition="WHERE a.role='subject'",
        selection="",
    )


def _vector_sql(
    observation: ObservationFilter,
    parameters: list[Any],
    *,
    chunk_condition: str,
    selection: str,
) -> tuple[str, str]:
    binding = f"${len(parameters) + 1}::jsonb"
    predicate = observation.relation_predicate(binding, "(c.document->'relations'->e.relation_index)")
    if binding in predicate:
        parameters.append(json.dumps(observation.to_dict()))
    # 표현 수가 장소 점수를 부풀리지 않도록 바깥 쿼리에서도 최고 점수만 사용한다.
    join = f"""CROSS JOIN LATERAL (
        SELECT vectors.embedding, vectors.relation_index, vectors.retrieval_path
        FROM (
            SELECT c.embedding, NULL::integer AS relation_index, '{RetrievalPath.CHUNK.value}'::text AS retrieval_path
            {chunk_condition}
            UNION ALL
            SELECT e.embedding, e.relation_index, '{RetrievalPath.RELATION.value}'::text AS retrieval_path
            FROM retrieval_relation_embeddings e
            WHERE e.chunk_id=c.chunk_id AND e.context_version=c.context_version
              AND e.representation_version='{VectorRepresentation.RELATION_QUOTE.value}'
              AND e.embedding_model='BAAI/bge-m3' AND {predicate}
        ) vectors
        WHERE vectors.embedding IS NOT NULL
        {selection}
    ) selected_vector"""
    extension = " || jsonb_strip_nulls(jsonb_build_object('retrieval_path', selected_vector.retrieval_path, 'retrieved_relation_index', selected_vector.relation_index))"
    return join, extension
