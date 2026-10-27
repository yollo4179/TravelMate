"""Explicit offline collection/application; the recommendation path never calls Perplexity."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import asynccontextmanager
import json
import os
from pathlib import Path
import sys
from typing import Any, AsyncIterator

import httpx

from .agent import AgentClient, AgentSettings
from .artifacts import collect_place
from .contracts import CollectionStatus, ExistingPlace
from .repository import apply_record, ensure_schema, existing_places


@asynccontextmanager
async def database_pool() -> AsyncIterator[Any]:
    import asyncpg

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise ValueError("DATABASE_URL must point to the FastAPI-owned search database")
    pool = await asyncpg.create_pool(dsn=database_url, min_size=1, max_size=1, command_timeout=30)
    try:
        yield pool
    finally:
        await pool.close()


def read_places(path: Path, identifiers: list[int] | None) -> list[ExistingPlace]:
    text = path.read_text(encoding="utf-8-sig")
    documents = [json.loads(line) for line in text.splitlines() if line.strip()] if path.suffix == ".jsonl" else json.loads(text)
    if not isinstance(documents, list):
        raise ValueError("Place input must be a JSON array or JSONL of existing place records")
    places = [ExistingPlace.from_mapping(row) for row in documents]
    if len({place.place_id for place in places}) != len(places):
        raise ValueError("Duplicate place IDs in input")
    selected = [place for place in places if identifiers is None or place.place_id in identifiers]
    if identifiers is not None and {place.place_id for place in selected} != set(identifiers):
        raise ValueError("Some selected place IDs are absent from the input")
    if not selected:
        raise ValueError("No existing places selected")
    return selected


async def collect(args: argparse.Namespace) -> int:
    identifiers = args.place_ids if not args.all_existing else None
    if args.input is not None:
        places = read_places(args.input, identifiers)
    else:
        async with database_pool() as pool:
            places = await existing_places(pool, identifiers)
    if not places:
        raise ValueError("No existing places selected")
    settings = AgentSettings(
        preset=args.preset if args.preset else None if args.model else os.environ.get("PERPLEXITY_AGENT_PRESET") or None,
        model=args.model if args.model else None if args.preset else os.environ.get("PERPLEXITY_AGENT_MODEL") or None,
        api_key=os.environ.get("PERPLEXITY_API_KEY", ""), timeout_seconds=args.timeout,
    )
    if args.execute and not settings.api_key.strip():
        raise ValueError("PERPLEXITY_API_KEY is required with --execute")
    status = 0
    async with httpx.AsyncClient() as http:
        client = AgentClient(http, settings) if args.execute else None
        for place in places:
            path = await collect_place(place, settings, args.output, client, refresh=args.refresh)
            record = json.loads(path.read_text(encoding="utf-8"))
            print(json.dumps({"place_id": place.place_id, "status": record["status"], "http_status": record.get("http_status"), "searchable_claim_count": record.get("searchable_claim_count"), "record": str(path)}, ensure_ascii=False), flush=True)
            if record["status"] == CollectionStatus.FAILED:
                status = 1
                if record.get("http_status") in (401, 403, 429):
                    print("Collection stopped on authentication/rate limit response; remaining places were not attempted.", file=sys.stderr)
                    break
    return status


async def apply(args: argparse.Namespace) -> int:
    async with database_pool() as pool:
        await ensure_schema(pool)
        status = await apply_record(pool, args.record)
    print(status)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    collection = commands.add_parser("collect")
    inputs = collection.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--from-search-db", action="store_true")
    scope = collection.add_mutually_exclusive_group(required=True)
    scope.add_argument("--place-id", action="append", type=int, dest="place_ids")
    scope.add_argument("--all-existing", action="store_true")
    selector = collection.add_mutually_exclusive_group()
    selector.add_argument("--preset")
    selector.add_argument("--model")
    collection.add_argument("--output", type=Path, required=True)
    collection.add_argument("--execute", action="store_true", help="Make metered API calls; otherwise only archive the proposed request")
    collection.add_argument("--refresh", action="store_true", help="Explicitly bypass the matching collection cache")
    collection.add_argument("--timeout", type=float, default=120.0)
    application = commands.add_parser("apply")
    application.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    if args.env_file is not None:
        from dotenv import load_dotenv
        if not args.env_file.is_file():
            parser.error("The explicit environment file does not exist")
        load_dotenv(args.env_file, override=False)
    if args.command == "collect":
        datasets = Path(__file__).resolve().parents[3] / "Evaluation/datasets"
        if args.output.resolve().is_relative_to(datasets.resolve()):
            parser.error("Collection output must be outside frozen evaluation datasets")
    try:
        raise SystemExit(asyncio.run(collect(args) if args.command == "collect" else apply(args)))
    except Exception as exception:
        print(f"Enrichment command failed: {type(exception).__name__}", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
