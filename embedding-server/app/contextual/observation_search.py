"""명시한 내용 종류와 이동 방향으로 근거를 제한한다. 자연어에서 조건을 추측하지 않는다."""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from .contracts import ContentKind


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

    @classmethod
    def from_mapping(cls, value: dict[str, Any] | None) -> ObservationFilter | None:
        if value is None:
            return None
        if not isinstance(value, dict) or set(value) - {"content_kinds", "origin_place_id", "destination_place_id", "result_endpoint"}:
            raise ValueError("지원하지 않는 관찰 검색 조건입니다")
        if not value:
            return None
        identifiers = [value.get(key) for key in ("origin_place_id", "destination_place_id")]
        if any(identifier is not None and (type(identifier) is not int or not 0 < identifier <= 9223372036854775807) for identifier in identifiers):
            raise ValueError("이동 장소 ID는 양의 정수여야 합니다")
        kinds = value.get("content_kinds", [])
        if not isinstance(kinds, list) or any(not isinstance(kind, str) for kind in kinds) or len(set(kinds)) != len(kinds):
            raise ValueError("내용 종류는 중복 없는 배열이어야 합니다")
        kinds = tuple(ContentKind(kind) for kind in kinds)
        has_direction = any(identifier is not None for identifier in identifiers) or "result_endpoint" in value
        if not kinds and not has_direction:
            return None
        if has_direction:
            if kinds and ContentKind.MOVEMENT not in kinds:
                raise ValueError("이동 방향 조건에는 이동 내용이 필요합니다")
            kinds = (ContentKind.MOVEMENT,)
        default_side = EndpointSide.ORIGIN if identifiers[1] is not None else EndpointSide.DESTINATION if identifiers[0] is not None else EndpointSide.EITHER
        return cls(kinds, identifiers[0], identifiers[1], EndpointSide(value.get("result_endpoint", default_side)))

    def to_dict(self) -> dict[str, Any]:
        return {"content_kinds": [kind.value for kind in self.content_kinds],
                "origin_place_id": self.origin_place_id, "destination_place_id": self.destination_place_id,
                "result_endpoint": self.result_endpoint.value}

    def sql_predicate(self, parameters: list[Any]) -> str:
        parameters.append(json.dumps(self.to_dict()))
        binding = f"${len(parameters)}::jsonb"
        conditions = []
        if self.content_kinds:
            conditions.append(f"c.document->>'content_kind'=ANY(ARRAY(SELECT jsonb_array_elements_text({binding}->'content_kinds')))")
        edges = []
        for key, endpoint in (("origin_place_id", "origin"), ("destination_place_id", "destination")):
            if getattr(self, key) is not None:
                edges.append(f"(relation->'{endpoint}'->>'place_id')::bigint=({binding}->>'{key}')::bigint")
        if self.result_endpoint != EndpointSide.EITHER:
            edges.append(f"(relation->'{self.result_endpoint.value}'->>'place_id')::bigint=p.place_id")
        if edges and self.result_endpoint == EndpointSide.EITHER:
            edges.append("((relation->'origin'->>'place_id')::bigint=p.place_id OR "
                         "(relation->'destination'->>'place_id')::bigint=p.place_id)")
        if edges:
            conditions.append("EXISTS(SELECT 1 FROM jsonb_array_elements(COALESCE(c.document->'relations','[]'::jsonb)) relation WHERE "
                              + " AND ".join(edges) + ")")
        return " AND " + " AND ".join(conditions) if conditions else ""

    def matches(self, place_id: int, document: dict[str, Any] | None) -> bool:
        if not document or (self.content_kinds and document.get("content_kind") not in self.content_kinds):
            return False
        if self.origin_place_id is None and self.destination_place_id is None and self.result_endpoint == EndpointSide.EITHER:
            return True
        for relation in document.get("relations", []):
            if self.origin_place_id is not None and relation["origin"]["place_id"] != self.origin_place_id:
                continue
            if self.destination_place_id is not None and relation["destination"]["place_id"] != self.destination_place_id:
                continue
            if self.result_endpoint != EndpointSide.EITHER and relation[self.result_endpoint.value]["place_id"] != place_id:
                continue
            if self.result_endpoint == EndpointSide.EITHER and place_id not in (
                relation["origin"]["place_id"], relation["destination"]["place_id"]
            ):
                continue
            return True
        return False
