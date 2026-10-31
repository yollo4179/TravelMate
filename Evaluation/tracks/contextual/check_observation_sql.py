"""애플리케이션 테이블 없이 읽기 전용 VALUES 자료로 관찰 필터 SQL을 확인한다."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from pathlib import Path
import sys
from typing import Any


def cases() -> list[dict[str, Any]]:
    root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(root / "embedding-server"))
    from app.contextual.observation_search import ObservationFilter
    route = {"content_kind": "movement", "relations": [{"origin": {"place_id": 394, "name": "A공원"},
        "destination": {"place_id": 395, "name": "B공원"}, "conditions": [{"kind": "stairs", "quote": "계단"}]}]}
    mixed = {"content_kind": "landscape", "place_refs": [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "mentioned"}],
        "relations": [{**route["relations"][0], "type": "movement", "importance": "supporting",
                       "evidence": {"start": 0, "end": 2, "quote": "계단"}}]}
    result = []
    for name, condition, document, expected in (
        ("supporting_landscape_to_b", {"destination_place_id": 395}, mixed, [394]),
        ("supporting_landscape_from_a", {"origin_place_id": 394}, mixed, [395]),
        ("supporting_is_searchable", {"relation_importance": ["supporting"]}, mixed, [394, 395]),
        ("supporting_is_not_primary", {"relation_importance": ["primary"]}, mixed, []),
        ("b_does_not_inherit_landscape", {"content_kinds": ["landscape"]}, mixed, [394]),
        ("to_b_returns_a", {"destination_place_id": 395}, route, [394]),
        ("from_a_returns_b", {"origin_place_id": 394}, route, [395]),
        ("either_endpoint_is_scoped_to_matching_relation", {"destination_place_id": 395, "result_endpoint": "either"},
         {"content_kind": "movement", "relations": [
             {"origin": {"place_id": 396}, "destination": {"place_id": 395}, "conditions": []},
             {"origin": {"place_id": 394}, "destination": {"place_id": 397}, "conditions": []}]}, [395]),
        ("route_is_not_landscape", {"content_kinds": ["landscape"]}, route, []),
        ("route_is_not_facility", {"content_kinds": ["facility"]}, route, []),
        ("landscape_matches_kind", {"content_kinds": ["landscape"]}, {"content_kind": "landscape", "place_refs": [{"place_id": 394, "role": "subject"}, {"place_id": 395, "role": "subject"}]}, [394, 395]),
        ("unknown_origin_is_not_invented", {"destination_place_id": 395},
         {"content_kind": "movement", "relations": [{"origin": {"place_id": None, "name": "출발지 미상"},
             "destination": {"place_id": 395, "name": "B공원"}, "conditions": []}]}, []),
    ):
        parameters: list[Any] = [json.dumps(document), [394, 395]]
        predicate = ObservationFilter.from_mapping(condition).sql_predicate(parameters)
        query = "SELECT p.place_id FROM (SELECT $1::jsonb AS document)c CROSS JOIN unnest($2::bigint[])p(place_id) WHERE true" + predicate + " ORDER BY p.place_id"
        result.append({"name": name, "query": query, "parameters": parameters, "expected": expected})
    return result


async def execute(items: list[dict[str, Any]]) -> dict[str, Any]:
    import asyncpg
    connection = await asyncpg.connect(os.environ["DATABASE_URL"])
    results = []
    try:
        async with connection.transaction(readonly=True):
            for item in items:
                rows = await connection.fetch(item["query"], *item["parameters"])
                actual = [row["place_id"] for row in rows]
                if actual != item["expected"]:
                    raise ValueError("관찰 검색 SQL의 결과가 예상과 다릅니다")
                results.append({"name": item["name"], "passed": True})
    finally:
        await connection.close()
    return {"cases": results, "database_writes": 0, "application_tables_queried": False,
            "mode": "readonly-values"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--cases", type=Path)
    args = parser.parse_args()
    if args.execute:
        if args.cases is None:
            parser.error("실행할 고정 검사 파일이 필요합니다")
        print(json.dumps(asyncio.run(execute(json.loads(args.cases.read_text(encoding="utf-8")))), ensure_ascii=False))
    else:
        print(json.dumps(cases(), ensure_ascii=False))


if __name__ == "__main__":
    main()
