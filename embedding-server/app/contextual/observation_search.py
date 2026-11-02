"""관찰 주체와 이동 관계를 서로 다른 기준으로 검색한다."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from .contracts import ContentKind, PlaceRole
from .relations import RelationImportance, RelationType, RetrievalScope


class EndpointSide(StrEnum):
    ORIGIN = "origin"
    DESTINATION = "destination"
    EITHER = "either"


@dataclass(frozen=True)
class ObservationFilter:
    content_kinds: tuple[ContentKind, ...] = ()
    origin_place_id: int | None = None
    destination_place_id: int | None = None
    result_endpoint: EndpointSide = EndpointSide.EITHER
    relation_importance: tuple[RelationImportance, ...] = ()

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> ObservationFilter | None:
        if value is None:
            return None
        allowed = {"content_kinds", "origin_place_id", "destination_place_id", "result_endpoint", "relation_importance"}
        if not isinstance(value, dict) or set(value) - allowed:
            raise ValueError("지원하지 않는 관찰 검색 조건입니다")
        if not value:
            return None
        identifiers = [value.get(key) for key in ("origin_place_id", "destination_place_id")]
        if any(identifier is not None and (type(identifier) is not int or not 0 < identifier <= 9223372036854775807) for identifier in identifiers):
            raise ValueError("이동 장소 ID는 양의 정수여야 합니다")
        kinds = cls._enum_values(value.get("content_kinds", []), ContentKind)
        importance = cls._enum_values(value.get("relation_importance", []), RelationImportance)
        has_direction = any(identifier is not None for identifier in identifiers) or "result_endpoint" in value
        if not kinds and not has_direction and not importance:
            return None
        if has_direction or importance:
            if kinds and ContentKind.MOVEMENT not in kinds:
                raise ValueError("이동 방향·비중 조건에는 이동 검색이 필요합니다")
            kinds = (ContentKind.MOVEMENT,)
        default_side = EndpointSide.ORIGIN if identifiers[1] is not None else EndpointSide.DESTINATION if identifiers[0] is not None else EndpointSide.EITHER
        return cls(
            kinds,
            identifiers[0],
            identifiers[1],
            EndpointSide(value.get("result_endpoint", default_side)),
            importance,
        )

    @staticmethod
    def _enum_values(values: Any, enumeration: type[StrEnum]) -> tuple[Any, ...]:
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values) or len(set(values)) != len(values):
            raise ValueError("검색 종류·관계 비중은 중복 없는 배열이어야 합니다")
        return tuple(enumeration(value) for value in values)

    @property
    def includes_relations(self) -> bool:
        return (ContentKind.MOVEMENT in self.content_kinds or self.origin_place_id is not None
                or self.destination_place_id is not None or self.result_endpoint != EndpointSide.EITHER
                or bool(self.relation_importance))

    @property
    def active_role_sql(self) -> str:
        return "a.role IN ('subject','relation_endpoint')" if self.includes_relations else "a.role='subject'"

    def to_dict(self) -> dict[str, Any]:
        return {"content_kinds": [kind.value for kind in self.content_kinds],
                "origin_place_id": self.origin_place_id, "destination_place_id": self.destination_place_id,
                **({"result_endpoint": self.result_endpoint.value} if self.includes_relations else {}),
                **({"relation_importance": [importance.value for importance in self.relation_importance]} if self.relation_importance else {})}

    def sql_predicate(self, parameters: list[Any]) -> str:
        binding = f"${len(parameters) + 1}::jsonb"
        alternatives = []
        main_kinds = [kind for kind in self.content_kinds if kind != ContentKind.MOVEMENT]
        if main_kinds:
            alternatives.append(f"(c.document->>'content_kind'=ANY(ARRAY(SELECT jsonb_array_elements_text({binding}->'content_kinds'))) "
                                "AND c.document->>'content_kind'<>'movement' AND c.document->'place_refs' @> jsonb_build_array(jsonb_build_object('place_id',p.place_id,'role','subject')))")
        if self.includes_relations:
            alternatives.append("EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(c.document->'relations','[]'::jsonb)) relation WHERE "
                                + self.relation_predicate(binding) + ")")
        predicate = " AND (" + " OR ".join(alternatives) + ")" if alternatives else ""
        if binding in predicate:
            parameters.append(json.dumps(self.to_dict()))
        return predicate

    def relation_predicate(self, binding: str, relation: str = "relation") -> str:
        edges = [f"({relation}->>'type'='movement' OR ({relation}->>'type' IS NULL AND c.document->>'content_kind'='movement'))"]
        for key, endpoint in (("origin_place_id", "origin"), ("destination_place_id", "destination")):
            if getattr(self, key) is not None:
                edges.append(f"({relation}->'{endpoint}'->>'place_id')::bigint=({binding}->>'{key}')::bigint")
        if self.result_endpoint == EndpointSide.EITHER:
            edges.append(f"(({relation}->'origin'->>'place_id')::bigint=p.place_id OR ({relation}->'destination'->>'place_id')::bigint=p.place_id)")
        else:
            edges.append(f"({relation}->'{self.result_endpoint.value}'->>'place_id')::bigint=p.place_id")
        if self.relation_importance:
            edges.append(f"{relation}->>'importance'=ANY(ARRAY(SELECT jsonb_array_elements_text({binding}->'relation_importance')))")
        return " AND ".join(edges)

    def matched_relations(self, place_id: int, document: dict[str, Any]) -> list[dict[str, Any]]:
        if not self.includes_relations:
            return []
        matches = []
        for relation in document.get("relations", []):
            if relation.get("type") != RelationType.MOVEMENT and not (relation.get("type") is None and document.get("content_kind") == ContentKind.MOVEMENT):
                continue
            if self.relation_importance and relation.get("importance") not in self.relation_importance:
                continue
            if self.origin_place_id is not None and relation["origin"]["place_id"] != self.origin_place_id:
                continue
            if self.destination_place_id is not None and relation["destination"]["place_id"] != self.destination_place_id:
                continue
            if self.result_endpoint == EndpointSide.EITHER:
                if place_id not in (relation["origin"]["place_id"], relation["destination"]["place_id"]):
                    continue
            elif relation[self.result_endpoint.value]["place_id"] != place_id:
                continue
            matches.append(relation)
        return matches

    def matches_observation(self, place_id: int, document: dict[str, Any]) -> bool:
        return (document.get("content_kind") != ContentKind.MOVEMENT
                and document.get("content_kind") in self.content_kinds
                and any(ref["place_id"] == place_id and ref["role"] == PlaceRole.SUBJECT for ref in document.get("place_refs", [])))

    def matches(self, place_id: int, document: dict[str, Any] | None) -> bool:
        return bool(document and (self.matches_observation(place_id, document) or self.matched_relations(place_id, document)))

    def scope_evidence(self, place_id: int, document: dict[str, Any]) -> dict[str, Any]:
        if self.matches_observation(place_id, document) and "retrieved_relation_index" not in document:
            return document
        relations = self.matched_relations(place_id, document)
        if "retrieved_relation_index" in document:
            index = document["retrieved_relation_index"]
            original = document.get("relations", [])
            if type(index) is not int or not 0 <= index < len(original) or original[index] not in relations:
                raise ValueError("직접 검색한 관계와 방향·비중 조건이 일치하지 않습니다")
            relations = [original[index]]
        if not relations:
            raise ValueError("선택한 장소와 일치하는 이동 근거가 없습니다")
        quotations = [
            f"출발지: {relation['origin']['name']} → 도착지: {relation['destination']['name']}\n"
            + relation.get("evidence", {}).get("quote", document["chunk_text"])
            for relation in relations
        ]
        # 혼합 청크 전체를 목적지의 경관 근거로 리랭커에 넘기지 않는다. 보존 원문은 그대로 둔다.
        return {**document, "retrieval_scope": RetrievalScope.RELATION, "matched_relations": relations,
                "search_text": "이동 관계 근거\n" + "\n".join(dict.fromkeys(quotations))}

    def scope_rows(self, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        scoped = []
        for row in rows:
            evidence = row.get("evidence")
            document = json.loads(evidence) if isinstance(evidence, str) else evidence
            if document is None:
                raise ValueError("명시적 관찰 검색에는 선택 근거가 필요합니다")
            document = self.scope_evidence(row["place_id"], document)
            scoped.append({**row, "evidence": document,
                           **({"description": document["search_text"]} if "search_text" in document else {})})
        return scoped
