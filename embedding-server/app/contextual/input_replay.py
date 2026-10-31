"""지시문 비교와 구분하여, 청크 원문 추가만 허용하는 입력 형식 비교."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from app.enrichment.artifacts import write_json
from app.enrichment.contracts import CollectionStatus, fingerprint
from .artifacts import load_record
from .input_format import InputVersion, explicit_chunks
from .replay import GenerationBaseline
from .validation import current_validation_version


class InputFormatComparison:
    def __init__(self, baseline: GenerationBaseline) -> None:
        if baseline.record.get("input_version", InputVersion.OFFSETS) != InputVersion.OFFSETS:
            raise ValueError("입력 형식 비교의 대조군은 기존 위치 기반 입력이어야 합니다")
        if baseline.record.get("validation_version") != current_validation_version(baseline.record["prompt_version"]):
            raise ValueError("입력 형식만 비교하려면 대조군 응답을 현재 규칙으로 먼저 무료 재검증해야 합니다")
        self.baseline = baseline

    def candidate_request(self, prompt_version: str) -> dict[str, Any]:
        if prompt_version != self.baseline.record["prompt_version"]:
            raise ValueError("입력 형식 비교에서는 프롬프트 버전을 바꿀 수 없습니다")
        candidate = deepcopy(self.baseline.request)
        original = json.loads(candidate["input"])
        if any("chunk_text" in span for span in original["spans"]):
            raise ValueError("대조군에는 명시적 청크 원문이 없어야 합니다")
        candidate["input"] = json.dumps(explicit_chunks(original), ensure_ascii=False)
        return candidate

    def verify_request(self, candidate: dict[str, Any]) -> None:
        expected = self.candidate_request(self.baseline.record["prompt_version"])
        if candidate != expected:
            raise ValueError("입력 형식 비교는 청크 원문 추가 이외의 변경을 허용하지 않습니다")

    def write_report(self, result_path: Path, *, output_directory: Path | None = None) -> Path:
        record = json.loads(result_path.read_text(encoding="utf-8"))
        request = json.loads(result_path.with_name("request.json").read_text(encoding="utf-8"))
        self.verify_request(request)
        if (record.get("input_version") != InputVersion.EXPLICIT
                or record["prompt_version"] != self.baseline.record["prompt_version"]
                or record.get("request_profile_id") != self.baseline.request_profile_id):
            raise ValueError("입력 형식 비교의 실행 메타데이터가 다릅니다")
        actual_model = None
        if record["status"] == CollectionStatus.COLLECTED:
            load_record(result_path)
            actual_model = record["actual_model"]
        report = {
            "comparison_kind": "input-format-only",
            "baseline_request_hash": self.baseline.record["request_hash"],
            "candidate_request_hash": record["request_hash"],
            "baseline_input_version": InputVersion.OFFSETS.value,
            "candidate_input_version": InputVersion.EXPLICIT.value,
            "prompt_version": record["prompt_version"],
            "instructions_changed": False,
            "input_changed": True,
            "unchanged_request_fields": sorted(key for key in request if key != "input"),
            "source_text_and_spans_match": True,
            "actual_model_match": (actual_model == self.baseline.actual_model if actual_model else None),
            "validation_versions_match": record.get("validation_version") == self.baseline.record.get("validation_version"),
            "semantic_quality_evaluated": False,
        }
        directory = output_directory if output_directory is not None else result_path.parent / "input-comparisons"
        destination = directory / f"{fingerprint(report)}.json"
        try:
            write_json(destination, report)
        except FileExistsError:
            if json.loads(destination.read_text(encoding="utf-8")) != report:
                raise ValueError("기존 입력 비교 보고서가 달라졌습니다") from None
        return destination
