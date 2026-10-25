"""Evaluate recorded agent traces; evaluation never invokes or mutates application tools."""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter, defaultdict
import json
from pathlib import Path
from typing import Any

from common.dataset.build import check
from common.dataset.contracts import ExecutionStatus, ResponseType
from common.judge.runner import JudgeSettings, score_message
from tracks.end_to_end.score import evaluate_record
from common.dataset.io import digest, export_inputs, read_json, read_jsonl, write_json, write_jsonl

from common.paths import DEFAULT_DATASET, EVALUATION_ROOT, rubric_path
from .run_record import allocate_run, update_latest, write_run_record
from .tracks import Track, matches_track, metric_is_selected

ROOT = DEFAULT_DATASET


def selected_cases(root: Path, group: str | None, split: str, kinds: list[str] | None, tracks: list[str] | None) -> list[dict[str, Any]]:
    cases = read_jsonl(root / "generated/golden.jsonl")
    source_tracks = {"message" if name == "persona" else name for name in (tracks or [])}
    return [
        case for case in cases
        if (group is None or case["evaluation_group"] == group)
        and (split == "all" or case["split"] == split)
        and (not kinds or case["expected_response_type"] in kinds)
        and (not source_tracks or set(case["evaluation_tracks"]).intersection(source_tracks))
    ]


def metric_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    values: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        for name, value in row["code"]["metrics"].items():
            if value is not None:
                values[name].append(float(value))
        for item in row.get("judge", {}).get("judgments", []):
            if item["applicable"]:
                values["gpt_" + item["criterion"]].append(float(item["score"]))
    return {name: {"mean": sum(scores) / len(scores), "evaluated_count": len(scores)} for name, scores in sorted(values.items())}


async def evaluate(
    *,
    root: Path,
    group: str | None,
    cases: list[dict[str, Any]],
    responses_path: Path,
    output: Path,
    use_judge: bool,
    settings: JudgeSettings,
    precheck_only: bool = False,
    track: Track = Track.END_TO_END,
) -> int:
    if output.resolve().is_relative_to(root.resolve()) or output.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
        raise ValueError("Evaluation results must be outside the dataset directory")
    if any((output / name).exists() for name in ("precheck.json", "summary.json", "scores/results.jsonl")):
        raise FileExistsError("An evaluation run cannot overwrite an existing report")
    corpus = {place["id"]: place for place in read_json(root / "generated/corpus.json")}
    inputs = {
        row["case_id"]: row for row in export_inputs(
            cases, corpus, persona_profile=read_json(root / "source/persona/guide_v1.json"),
        )
    }
    records = read_jsonl(responses_path)
    if len({record["case_id"] for record in records}) != len(records):
        raise ValueError("Duplicate response case IDs")
    known = {case["case_id"] for case in read_jsonl(root / "generated/golden.jsonl")}
    if any(record["case_id"] not in known for record in records):
        raise ValueError("Unknown response case ID")
    indexed = {record["case_id"]: record for record in records}
    invalid: dict[str, str] = {}
    valid = []
    for case in cases:
        record = indexed.get(case["case_id"])
        if record is None:
            invalid[case["case_id"]] = "response_missing"
        elif record.get("input_sha256") != inputs[case["case_id"]]["input_sha256"]:
            invalid[case["case_id"]] = "input_hash_missing_or_mismatch"
        elif not isinstance(record.get("tool_calls"), list) or "response" not in record:
            invalid[case["case_id"]] = "record_requires_response_and_explicit_tool_calls_array"
        else:
            valid.append((case, record))
    precheck = {
        "dataset_version": "1.4.0", "evaluation_group": group, "track": track.value,
        "selected_case_count": len(cases), "valid_response_count": len(valid),
        "invalid_or_missing": invalid,
        "judge_requested": use_judge, "judge_model": settings.model,
        "api_key_present": bool(settings.api_key), "llm_connection_verified": False,
        "dataset_manifest_sha256": digest(root / "manifest.json"),
        "responses_sha256": digest(responses_path),
        "responses_file": str(responses_path),
        "reference_required": use_judge,
        "reference_available_count": sum(bool(case["reference"]) for case in cases),
    }
    selected_ids = {case["case_id"] for case in cases}
    write_jsonl(output / "outputs/records.jsonl", [record for record in records if record["case_id"] in selected_ids])
    write_json(output / "precheck.json", precheck)
    if precheck_only:
        return 0 if valid and (not use_judge or settings.api_key) else 2
    if not valid or (use_judge and not settings.api_key):
        write_json(output / "summary.json", {**precheck, "status": "not_run", "result_count": 0})
        return 2
    rubrics = {name: rubric_path(root, name).read_text(encoding="utf-8") for name in {case["evaluation_group"] for case in cases}}
    results = []
    client = None
    judge_blocked_error: str | None = None
    if use_judge:
        from openai import AsyncOpenAI
        client = AsyncOpenAI(api_key=settings.api_key)
    try:
        for case, record in valid:
            row = {
                "case_id": case["case_id"], "evaluation_tracks": case["evaluation_tracks"],
                "evaluation_group": case["evaluation_group"],
                "target_model": record.get("model", "not_recorded"),
                "response": record["response"],
                "tool_calls": record["tool_calls"],
                "expected_response_type": case["expected_response_type"],
                "actual_response_type": record["response"].get("type") if isinstance(record["response"], dict) else None,
                "input_sha256": record["input_sha256"],
                "code": evaluate_record(case, record),
            }
            row["code"]["metrics"] = {
                name: value for name, value in row["code"]["metrics"].items()
                if metric_is_selected(name, track)
            }
            if use_judge:
                if judge_blocked_error:
                    row.update(judge_status=ExecutionStatus.NOT_RUN.value, judge_error_type=judge_blocked_error)
                else:
                    try:
                        row["judge"] = await score_message(case, record, inputs[case["case_id"]]["model_input"], rubrics[case["evaluation_group"]], settings, client=client)
                        row["judge_status"] = ExecutionStatus.COMPLETED.value
                    except Exception as exception:
                        error_type = type(exception).__name__
                        row.update(judge_status=ExecutionStatus.FAILED.value, judge_error_type=error_type)
                        if error_type in ("AuthenticationError", "PermissionDeniedError", "RateLimitError"):
                            judge_blocked_error = error_type
            results.append(row)
            print(f"{track.value}: {case['case_id']} ({len(results)}/{len(valid)})", flush=True)
    finally:
        if client is not None:
            await client.close()
    summary = {
        **precheck,
        "status": "completed" if not invalid and all(row.get("judge_status", "completed") == "completed" for row in results) else "partial",
        "result_count": len(results),
        "code_metrics_and_gpt_scores": metric_summary(results),
        "by_response_type": {
            kind.value: metric_summary([row for row in results if row["expected_response_type"] == kind])
            for kind in ResponseType
        },
        "type_confusion": dict(Counter(f"{row['expected_response_type']}->{row['actual_response_type']}" for row in results)),
        "judge_rubric_sha256": {name: digest(rubric_path(root, name)) for name in rubrics} if use_judge else None,
        "judge_success_count": sum(row.get("judge_status") == "completed" for row in results),
        "llm_connection_verified": any(row.get("judge_status") == "completed" for row in results),
        "notes": [
            "Missing/invalid records are coverage failures, not silently converted into incorrect model answers.",
            "Unobserved backend state and unavailable route checks have null scores and separate denominators.",
            "Search and memory recall use their own query-specific relevant ID sets.",
            "GPT criteria use 0..3 scores and are not Ragas built-in AnswerCorrectness scores.",
        ],
    }
    write_jsonl(output / "scores/results.jsonl", results)
    write_json(output / "summary.json", summary)
    return 0 if summary["status"] == "completed" else 1


def main(track_name: str) -> None:
    track = Track(track_name)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", "--root", dest="root", type=Path, default=ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check")
    export = commands.add_parser("export-inputs")
    score = commands.add_parser("evaluate")
    for command in (export, score):
        command.add_argument("--split", choices=("development", "test", "all"), required=True)
        command.add_argument("--type", choices=[kind.value for kind in ResponseType], action="append", dest="kinds")
        command.add_argument("--track", action="append", dest="tracks")
        command.add_argument("--group", choices=("plannerLLM", "managerLLM"), help="Optional original case-batch filter; not a model selection")
    export.add_argument("--output", type=Path, required=True)
    score.add_argument("--responses", type=Path, required=True)
    score.add_argument("--output-dir", type=Path)
    score.add_argument("--env-file", type=Path)
    score.add_argument("--judge", action="store_true")
    score.add_argument("--precheck-only", action="store_true")
    args = parser.parse_args()
    report = check(args.root)
    if args.command == "check":
        selected = [case for case in read_jsonl(args.root / "generated/golden.jsonl") if matches_track(case, track)]
        print(json.dumps({"status": "passed", "track": track.value, "case_count": len(selected), "dataset_case_count": report["case_count"]}, ensure_ascii=False))
        return
    cases = [case for case in selected_cases(args.root, args.group, args.split, args.kinds, args.tracks) if matches_track(case, track)]
    if not cases:
        parser.error("The explicit split/type/track selection contains no cases")
    corpus = {place["id"]: place for place in read_json(args.root / "generated/corpus.json")}
    if args.command == "export-inputs":
        if args.output.resolve().is_relative_to(args.root.resolve()) or args.output.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
            parser.error("Exported runtime inputs must be outside the versioned dataset")
        if args.output.exists():
            parser.error("Input export refuses to overwrite an existing file")
        write_jsonl(args.output, export_inputs(
            cases, corpus, persona_profile=read_json(args.root / "source/persona/guide_v1.json"),
        ))
        print(f"Exported {len(cases)} inputs; references/judgments/expectations were not sent to the tested agent.")
        return
    settings = JudgeSettings.load(args.root, args.env_file)
    run_id, output = allocate_run(track, args.root, args.output_dir)
    scope = {"split": args.split, "types": args.kinds, "tracks": args.tracks, "group": args.group, "selected_case_count": len(cases), "judge_requested": args.judge, "judge_model": settings.model}
    write_run_record(run_id=run_id, track=track, dataset=args.root, output=output, scope=scope, status="started")
    try:
        code = asyncio.run(evaluate(
            root=args.root, group=args.group, cases=cases, responses_path=args.responses,
            output=output, use_judge=args.judge, settings=settings, precheck_only=args.precheck_only,
            track=track,
        ))
    except Exception:
        write_run_record(run_id=run_id, track=track, dataset=args.root, output=output, scope=scope, status="failed")
        raise
    status = "precheck_only" if args.precheck_only else read_json(output / "summary.json")["status"]
    write_run_record(run_id=run_id, track=track, dataset=args.root, output=output, scope=scope, status=status)
    if not args.precheck_only:
        update_latest(track, args.root, run_id, output)
    print(f"Reports: {output}")
    raise SystemExit(code)
