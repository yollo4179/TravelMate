"""유료 호출 없이 명시적 청크 입력과 구조 기반 분할 후보를 준비한다."""
from __future__ import annotations

import argparse
from datetime import UTC, datetime
from enum import StrEnum
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any

REPOSITORY = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPOSITORY / "embedding-server"))
from app.contextual.input_format import InputVersion
from app.contextual.input_replay import InputFormatComparison
from app.contextual.pipeline import split_source
from app.contextual.replay import GenerationBaseline
from app.contextual.contracts import SourceDocument
from app.enrichment.artifacts import write_json


class CandidateSplitterVersion(StrEnum):
    STRUCTURAL = "structural-boundaries-candidate-v2"


# 의미나 장소 역할을 추정하지 않고 원문에 있는 구조만 경계 후보로 쓴다.
BOUNDARIES = (
    re.compile(r"\r?\n[ \t]*(?:\r?\n)+"),
    re.compile(r"(?m)^[ \t]*(?:\.{3,}|…+)[ \t]*(?:\r?\n|$)"),
    re.compile(r"(?m)^[ \t]*(?:#{1,6}[ \t]+[^\r\n]+|\*\*[^\r\n]+\*\*[ \t]*)(?:\r?\n|$)"),
    re.compile(r"(?<=[.!?。！？])[ \t]+(?=\S)"),
)


def structural_candidates(source: SourceDocument) -> list[dict[str, Any]]:
    boundaries = {0, len(source.text)}
    for pattern in BOUNDARIES:
        for match in pattern.finditer(source.text):
            boundaries.add(match.start() if pattern is BOUNDARIES[2] else match.end())
    candidates = []
    for parent_start, parent_end in split_source(source):
        cuts = sorted({parent_start, parent_end} | {offset for offset in boundaries if parent_start < offset < parent_end})
        pieces = [(start, end) for start, end in zip(cuts, cuts[1:])]
        # 공백도 버리지 않으므로 이어 붙이면 기존 청크와 정확히 같아야 한다.
        if "".join(source.text[start:end] for start, end in pieces) != source.text[parent_start:parent_end]:
            raise ValueError("분할 후보가 기존 원문을 보존하지 못했습니다")
        candidates.extend({
            "source_id": source.source_id,
            "source_version": source.source_version,
            "parent_span": {"start": parent_start, "end": parent_end},
            "source_span": {"start": start, "end": end, "unit": "unicode_codepoint"},
            "chunk_text": source.text[start:end],
            "splitter_version": CandidateSplitterVersion.STRUCTURAL.value,
            "attribution_evaluated": False,
            "indexable": False,
        } for start, end in pieces)
    return candidates


def prepare(record_path: Path, output: Path) -> Path:
    output = output.resolve()
    record_path = record_path.resolve()
    if output.is_relative_to((REPOSITORY / "Evaluation/datasets").resolve()):
        raise ValueError("동결 평가 데이터 안에는 실행 자료를 쓰지 않습니다")
    if output.exists():
        raise ValueError("기존 실행 폴더를 덮어쓰지 않습니다")
    baseline = GenerationBaseline.load(record_path)
    comparison = InputFormatComparison(baseline)
    request = comparison.candidate_request(baseline.record["prompt_version"])
    comparison.verify_request(request)
    candidates = [candidate for source in baseline.bundle.sources for candidate in structural_candidates(source)]
    originals = {name: hashlib.sha256(record_path.with_name(name).read_bytes()).hexdigest()
                 for name in ("request.json", "record.json", "sources.json", "raw_response.json")}
    output.mkdir(parents=True)
    write_json(output / "request.explicit.json", request)
    write_json(output / "split-candidates.json", {"candidates": candidates})
    destination = output / "plan.json"
    write_json(destination, {
        "created_at": datetime.now(UTC).isoformat(),
        "baseline_record": str(record_path),
        "baseline_file_sha256": originals,
        "comparison_kind": "input-format-only",
        "input_version": InputVersion.EXPLICIT.value,
        "prompt_version": baseline.record["prompt_version"],
        "instructions_changed": False,
        "original_spans": sum(len(split_source(source)) for source in baseline.bundle.sources),
        "explicit_spans": len(json.loads(request["input"])["spans"]),
        "structural_candidates": len(candidates),
        "request_sha256": hashlib.sha256((output / "request.explicit.json").read_bytes()).hexdigest(),
        "split_candidates_sha256": hashlib.sha256((output / "split-candidates.json").read_bytes()).hexdigest(),
        "split_candidates_applied": False,
        "semantic_quality_evaluated": False,
        "api_calls": 0,
        "database_writes": 0,
    })
    return destination


def prepare_batch(summary_path: Path, output: Path) -> Path:
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    if not summary.get("comparison_complete") or not summary.get("results"):
        raise ValueError("완료된 생성 묶음이 필요합니다")
    results = summary["results"]
    identifiers = [row["id"] for row in results]
    if len(set(identifiers)) != len(identifiers) or any(not re.fullmatch(r"[A-Za-z0-9_-]+", name) for name in identifiers):
        raise ValueError("묶음 ID는 중복 없는 안전한 폴더명이어야 합니다")
    if output.exists():
        raise ValueError("기존 실행 폴더를 덮어쓰지 않습니다")
    plans = []
    for row in results:
        path = prepare(Path(row["candidate_record"]), output / row["id"])
        document = json.loads(path.read_text(encoding="utf-8"))
        plans.append({"id": row["id"], "plan": str(path),
                      "plan_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                      **{key: document[key] for key in ("original_spans", "explicit_spans", "structural_candidates")}})
    destination = output / "batch-plan.json"
    write_json(destination, {"created_at": datetime.now(UTC).isoformat(),
        "source_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "pairs": plans, "api_calls": 0, "database_writes": 0,
        "semantic_quality_evaluated": False, "split_candidates_applied": False})
    return destination


def audit_batch(batch_path: Path) -> dict[str, Any]:
    batch = json.loads(batch_path.read_text(encoding="utf-8"))
    identifiers = [row["id"] for row in batch["pairs"]]
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("중복 묶음은 여러 비교 입력으로 집계할 수 없습니다")
    verified_files = set()
    totals = {"pairs": 0, "original_spans": 0, "explicit_spans": 0, "structural_candidates": 0}
    for row in batch["pairs"]:
        plan_path = Path(row["plan"])
        if hashlib.sha256(plan_path.read_bytes()).hexdigest() != row["plan_sha256"]:
            raise ValueError("묶음 생성 후 개별 계획이 바뀌었습니다")
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
        record = Path(plan["baseline_record"])
        for name, expected in plan["baseline_file_sha256"].items():
            original = record.with_name(name)
            if hashlib.sha256(original.read_bytes()).hexdigest() != expected:
                raise ValueError("보존 원본의 해시가 달라졌습니다")
            verified_files.add(str(original))
        for name, key in (("request.explicit.json", "request_sha256"),
                          ("split-candidates.json", "split_candidates_sha256")):
            if hashlib.sha256(plan_path.with_name(name).read_bytes()).hexdigest() != plan[key]:
                raise ValueError("계획 생성 후 명시적 입력 또는 분할 후보가 바뀌었습니다")
        baseline = GenerationBaseline.load(record)
        request = json.loads(plan_path.with_name("request.explicit.json").read_text(encoding="utf-8"))
        InputFormatComparison(baseline).verify_request(request)
        candidates = json.loads(plan_path.with_name("split-candidates.json").read_text(encoding="utf-8"))["candidates"]
        expected = [candidate for source in baseline.bundle.sources for candidate in structural_candidates(source)]
        if candidates != expected:
            raise ValueError("분할 후보가 보존 원문의 구조 기반 분할과 다릅니다")
        counts = {"original_spans": sum(len(split_source(source)) for source in baseline.bundle.sources),
                  "explicit_spans": len(json.loads(request["input"])["spans"]),
                  "structural_candidates": len(candidates)}
        if any(plan[key] != value or row[key] != value for key, value in counts.items()):
            raise ValueError("실제 청크 수와 계획 집계가 다릅니다")
        totals["pairs"] += 1
        for key, value in counts.items():
            totals[key] += value
    if not totals["pairs"]:
        raise ValueError("빈 준비 묶음은 검증 완료로 표시하지 않습니다")
    return {**totals, "original_files_verified_unchanged": len(verified_files),
            "input_only_verified": True, "split_candidates_recomputed": True,
            "api_calls": 0, "database_writes": 0, "semantic_quality_evaluated": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--record", type=Path)
    source.add_argument("--generation-summary", type=Path)
    source.add_argument("--audit-batch", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    if arguments.audit_batch:
        if arguments.output:
            parser.error("감사는 입력을 읽기만 합니다. --output을 생략하세요")
        print(json.dumps(audit_batch(arguments.audit_batch), ensure_ascii=False))
        return
    if arguments.output is None:
        parser.error("준비에는 --output이 필요합니다")
    path = (prepare_batch(arguments.generation_summary, arguments.output) if arguments.generation_summary
            else prepare(arguments.record, arguments.output))
    print(str(path))


if __name__ == "__main__":
    main()
