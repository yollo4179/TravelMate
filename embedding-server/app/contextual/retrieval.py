"""검색 조건에 맞는 표현 전략과 원문 근거 범위를 함께 선택한다."""
from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Protocol

from .contracts import ContentKind
from .observation_search import ObservationFilter
from .relation_vectors import RetrievalPath, relation_vector_sql, semantic_relation_vector_sql


@dataclass(frozen=True)
class RetrievalSql:
    active_role: str
    observation: str = ""
    vector_join: str = ""
    evidence_extension: str = ""
    embedding: str = "c.embedding"
    relation_index: str = "NULL::integer"


class RetrievalStrategy(Protocol):
    def is_applicable(
        self,
        observation: ObservationFilter | None,
        use_relation_vectors: bool,
    ) -> bool: ...

    def build_sql(
        self,
        observation: ObservationFilter | None,
        parameters: list[Any],
    ) -> RetrievalSql: ...

    def scope_rows(
        self,
        rows: list[dict[str, Any]],
        observation: ObservationFilter | None,
    ) -> list[dict[str, Any]]: ...


class ChunkRetrievalStrategy:
    def is_applicable(
        self,
        observation: ObservationFilter | None,
        use_relation_vectors: bool,
    ) -> bool:
        return not use_relation_vectors or (observation is not None and not observation.includes_relations)

    def build_sql(
        self,
        observation: ObservationFilter | None,
        parameters: list[Any],
    ) -> RetrievalSql:
        return RetrievalSql(
            active_role=observation.active_role_sql if observation else "a.role='subject'",
            observation=observation.sql_predicate(parameters) if observation else "",
        )

    def scope_rows(
        self,
        rows: list[dict[str, Any]],
        observation: ObservationFilter | None,
    ) -> list[dict[str, Any]]:
        return observation.scope_rows(rows) if observation else rows


class FilteredRelationRetrievalStrategy(ChunkRetrievalStrategy):
    def is_applicable(
        self,
        observation: ObservationFilter | None,
        use_relation_vectors: bool,
    ) -> bool:
        return use_relation_vectors and observation is not None and observation.includes_relations

    def build_sql(
        self,
        observation: ObservationFilter | None,
        parameters: list[Any],
    ) -> RetrievalSql:
        if observation is None:
            raise ValueError("명시적 관계 검색에는 관찰 조건이 필요합니다")
        predicate = observation.sql_predicate(parameters)
        vector_join, extension = relation_vector_sql(observation, parameters)
        return RetrievalSql(
            active_role=observation.active_role_sql,
            observation=predicate,
            vector_join=vector_join,
            evidence_extension=extension,
            embedding="selected_vector.embedding",
            relation_index="selected_vector.relation_index",
        )


class SemanticRelationRetrievalStrategy:
    def is_applicable(
        self,
        observation: ObservationFilter | None,
        use_relation_vectors: bool,
    ) -> bool:
        return use_relation_vectors and observation is None

    def build_sql(
        self,
        observation: ObservationFilter | None,
        parameters: list[Any],
    ) -> RetrievalSql:
        vector_join, extension = semantic_relation_vector_sql(parameters)
        return RetrievalSql(
            active_role="a.role IN ('subject','relation_endpoint')",
            vector_join=vector_join,
            evidence_extension=extension,
            embedding="selected_vector.embedding",
            relation_index="selected_vector.relation_index",
        )

    def scope_rows(
        self,
        rows: list[dict[str, Any]],
        observation: ObservationFilter | None,
    ) -> list[dict[str, Any]]:
        movement = ObservationFilter(content_kinds=(ContentKind.MOVEMENT,))
        return [self._scope_row(row, movement) for row in rows]

    @staticmethod
    def _scope_row(
        row: dict[str, Any],
        movement: ObservationFilter,
    ) -> dict[str, Any]:
        evidence = row.get("evidence")
        document = json.loads(evidence) if isinstance(evidence, str) else evidence
        if not document:
            return row
        if document.get("retrieval_path") != RetrievalPath.RELATION:
            return {**row, "evidence": document}
        return movement.scope_rows([{**row, "evidence": document}])[0]


RETRIEVAL_STRATEGIES: tuple[RetrievalStrategy, ...] = (
    ChunkRetrievalStrategy(),
    FilteredRelationRetrievalStrategy(),
    SemanticRelationRetrievalStrategy(),
)


def resolve_retrieval_strategy(
    observation: ObservationFilter | None,
    use_relation_vectors: bool,
    strategies: tuple[RetrievalStrategy, ...] = RETRIEVAL_STRATEGIES,
) -> RetrievalStrategy:
    applicable = [
        strategy for strategy in strategies
        if strategy.is_applicable(observation, use_relation_vectors)
    ]
    if len(applicable) != 1:
        raise ValueError("검색 표현 전략은 정확히 하나여야 합니다")
    return applicable[0]
