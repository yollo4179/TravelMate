"""Generate contextual chunks from preserved TourAPI/blog/review sources; apply explicitly."""
from __future__ import annotations

import argparse
import asyncio
from contextlib import nullcontext
import json
import os
from pathlib import Path

import httpx

from app.enrichment.agent import AgentSettings
from app.enrichment.contracts import CollectionStatus
from app.enrichment.cli import database_pool
from app.enrichment.repository import ensure_schema as ensure_enrichment_schema
from .agent import DEFAULT_PRESET, PROMPT_VERSION
from .artifacts import SourceBundle, collect_bundle, revalidate_record
from .prompts import PromptVersion
from .profiles import ExecutionProfileId
from .replay import GenerationBaseline, revalidate_batch
from .repository import apply_bundle


async def run(args: argparse.Namespace) -> int:
    if args.command == "revalidate":
        if args.record.is_dir():
            report_path = revalidate_batch(args.record, args.output, baseline_profile=args.baseline_profile,
                                          paired_only=args.paired_only)
            report = json.loads(report_path.read_text(encoding="utf-8"))
            print(json.dumps({"report": str(report_path), "api_calls": 0, "records": len(report["records"]),
                              "failed": report["failed"], "comparisons": len(report["comparisons"])}, ensure_ascii=False))
            return int(report["failed"] != 0)
        path = revalidate_record(args.record, args.output, baseline_profile=args.baseline_profile)
        record = json.loads(path.read_text(encoding="utf-8"))
        print(json.dumps({"status": record["status"], "record": str(path), "api_calls": 0,
                          "validation_version": record["validation_version"],
                          "indexable_chunks": len(record["chunks"]),
                          "excluded_chunks": len(record["excluded_chunks"])}, ensure_ascii=False))
        return 0
    if args.command == "apply":
        async with database_pool() as pool:
            await ensure_enrichment_schema(pool)
            print(await apply_bundle(pool, args.record))
        return 0
    if args.baseline_profile and not args.baseline_record:
        raise ValueError("--baseline-profile requires --baseline-record")
    baseline = (GenerationBaseline.load(args.baseline_record, profile_id=args.baseline_profile)
                if args.baseline_record else None)
    prepared_request = None
    if baseline is not None:
        if args.preset or args.model:
            raise ValueError("Baseline comparisons reuse the recorded model selection; omit --preset and --model")
        bundle = baseline.bundle
        settings = baseline.settings(os.environ.get("PERPLEXITY_API_KEY", ""), args.timeout)
        prepared_request = baseline.candidate_request(args.prompt_version)
    else:
        bundle = (SourceBundle.from_enrichment_record(args.from_record) if args.from_record else
                  SourceBundle.from_mapping(json.loads(args.input.read_text(encoding="utf-8"))))
        model = args.model or os.environ.get("PERPLEXITY_AGENT_MODEL")
        preset = args.preset or (None if model else os.environ.get("PERPLEXITY_AGENT_PRESET") or DEFAULT_PRESET)
        if args.preset:
            model = None
        settings = AgentSettings(preset=preset, model=model, api_key=os.environ.get("PERPLEXITY_API_KEY", ""), timeout_seconds=args.timeout)
    if args.execute and not settings.api_key.strip():
        raise ValueError("Configure PERPLEXITY_API_KEY securely before --execute")
    client_context = httpx.AsyncClient() if args.execute else nullcontext(None)
    async with client_context as http:
        path = await collect_bundle(
            bundle,
            settings,
            args.output,
            http,
            refresh=args.refresh,
            prompt_version=args.prompt_version,
            prepared_request=prepared_request,
            request_profile_id=baseline.request_profile_id if baseline else None,
        )
    record = json.loads(path.read_text(encoding="utf-8"))
    summary = {"status": record["status"], "record": str(path), "prompt_version": record["prompt_version"]}
    if record.get("request_profile_id"):
        summary["request_profile_id"] = record["request_profile_id"]
    if baseline is not None:
        summary["comparison"] = str(baseline.write_report(path))
    print(json.dumps(summary, ensure_ascii=False))
    return int(record["status"] == CollectionStatus.FAILED)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path)
    commands = parser.add_subparsers(dest="command", required=True)
    collection = commands.add_parser("generate")
    inputs = collection.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--input", type=Path)
    inputs.add_argument("--from-record", type=Path)
    inputs.add_argument("--baseline-record", type=Path, help="Replay a validated contextual record, changing only the prompt")
    collection.add_argument("--baseline-profile", choices=[profile.value for profile in ExecutionProfileId],
                            help="Explicitly recognize a registered local baseline without rewriting its archive")
    collection.add_argument("--output", type=Path, default=Path("LocationReview"))
    selector = collection.add_mutually_exclusive_group()
    selector.add_argument("--preset")
    selector.add_argument("--model")
    collection.add_argument("--execute", action="store_true")
    collection.add_argument("--refresh", action="store_true")
    collection.add_argument("--timeout", type=float, default=120)
    collection.add_argument("--prompt-version", choices=[version.value for version in PromptVersion], default=PROMPT_VERSION)
    application = commands.add_parser("apply")
    application.add_argument("--record", type=Path, required=True)
    revalidation = commands.add_parser("revalidate", help="저장된 응답을 API 호출 없이 새 규칙으로 재검증")
    revalidation.add_argument("--record", type=Path, required=True, help="record.json 또는 일괄 재검증할 요청 아카이브 디렉터리")
    revalidation.add_argument("--output", type=Path, default=Path("LocationReview"))
    revalidation.add_argument("--baseline-profile", choices=[profile.value for profile in ExecutionProfileId])
    revalidation.add_argument("--paired-only", action="store_true", help="기존 비교 보고서에 연결된 요청만 일괄 재검증")
    args = parser.parse_args()
    if args.env_file:
        from dotenv import load_dotenv
        if not args.env_file.is_file():
            parser.error("Explicit environment file does not exist")
        load_dotenv(args.env_file, override=False)
    if args.command in ("generate", "revalidate"):
        datasets = Path(__file__).resolve().parents[3] / "Evaluation/datasets"
        if args.output.resolve().is_relative_to(datasets.resolve()):
            parser.error("Do not write into frozen evaluation datasets")
    try:
        raise SystemExit(asyncio.run(run(args)))
    except Exception as exception:
        print(f"Contextual command failed: {type(exception).__name__}")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
