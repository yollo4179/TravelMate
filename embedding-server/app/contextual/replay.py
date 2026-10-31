"""Reuse a validated request for controlled prompt comparisons."""
from __future__ import annotations

from dataclasses import dataclass
from copy import deepcopy
import json
from pathlib import Path
from typing import Any
import uuid

from jsonschema import ValidationError

from app.enrichment.agent import AgentSettings
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import CollectionStatus, fingerprint
from .artifacts import SourceBundle, load_record, revalidate_record
from .profiles import resolve_execution_profile
from .prompts import resolve_prompt
from .validation import ValidationVersion


@dataclass(frozen=True)
class GenerationBaseline:
    bundle: SourceBundle
    request: dict[str, Any]
    record: dict[str, Any]
    actual_model: str | None
    response_id: str | None
    request_profile_id: str | None = None

    @classmethod
    def load(cls, path: Path, *, profile_id: str | None = None) -> GenerationBaseline:
        bundle, _, record = load_record(path, baseline_profile=profile_id)
        request = json.loads(path.with_name("request.json").read_text(encoding="utf-8"))
        response = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
        return cls(
            bundle=bundle,
            request=request,
            record=record,
            actual_model=response.get("model"),
            response_id=response.get("id"),
            request_profile_id=record.get("request_profile_id") or profile_id,
        )

    def settings(self, api_key: str, timeout_seconds: float) -> AgentSettings:
        return AgentSettings(
            preset=self.request.get("preset"),
            model=self.request.get("model"),
            api_key=api_key,
            timeout_seconds=timeout_seconds,
        )

    def verify_request(self, candidate: dict[str, Any]) -> None:
        # Identical inputs include source spans, response schema and model selection.
        expected = {key: value for key, value in self.request.items() if key != "instructions"}
        actual = {key: value for key, value in candidate.items() if key != "instructions"}
        if actual != expected:
            raise ValueError("A prompt comparison may change instructions only")

    def candidate_request(self, prompt_version: str) -> dict[str, Any]:
        candidate = deepcopy(self.request)
        instructions = resolve_prompt(prompt_version).instructions
        if self.request_profile_id:
            instructions = resolve_execution_profile(self.request_profile_id).settings_for(prompt_version)["instructions"]
        candidate["instructions"] = instructions
        self.verify_request(candidate)
        return candidate

    def write_report(self, result_path: Path) -> Path:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        request = json.loads(result_path.with_name("request.json").read_text(encoding="utf-8"))
        self.verify_request(request)
        actual_model = None
        if result["status"] == CollectionStatus.COLLECTED:
            load_record(result_path, baseline_profile=self.request_profile_id)
            response = json.loads(result_path.with_name("raw_response.json").read_text(encoding="utf-8"))
            actual_model = response.get("model")
        baseline = {
            "request_hash": self.record["request_hash"],
            "prompt_version": self.record["prompt_version"],
            "actual_model": self.actual_model,
            "response_id": self.response_id,
            "request_profile_id": self.request_profile_id,
        }
        baseline_validation = self.record.get("validation_version", ValidationVersion.STRICT.value)
        candidate_validation = result.get("validation_version", ValidationVersion.STRICT.value)
        model_match = self.actual_model == actual_model if self.actual_model and actual_model else None
        report = {
            "baseline": baseline,
            "candidate": {
                "request_hash": result["request_hash"],
                "prompt_version": result["prompt_version"],
                "status": result["status"],
                "actual_model": actual_model,
                "request_profile_id": result.get("request_profile_id"),
            },
            "input_and_settings_match": True,
            "unchanged_request_fields": sorted(key for key in self.request if key != "instructions"),
            "instructions_changed": self.request["instructions"] != request["instructions"],
            "actual_model_match": model_match,
            "semantic_quality_evaluated": False,
        }
        if "validation_version" in self.record or "validation_version" in result:
            report.update(baseline_validation_version=baseline_validation, candidate_validation_version=candidate_validation,
                          validation_versions_match=baseline_validation == candidate_validation,
                          indexable_chunks=len(result.get("chunks", [])), excluded_chunks=len(result.get("excluded_chunks", [])))
        destination = result_path.parent / "comparisons" / f"{fingerprint(baseline)}.json"
        try:
            write_json(destination, report)
        except FileExistsError:
            if json.loads(destination.read_text(encoding="utf-8")) != report:
                raise ValueError("Existing comparison report changed") from None
        return destination


def revalidate_batch(
    directory: Path,
    output: Path,
    *,
    baseline_profile: str | None = None,
    paired_only: bool = False,
) -> Path:
    """재시도 성공 여부로 표본을 고르지 않고 요청별 최초 보존 응답을 한 번에 재검증한다."""
    candidates: dict[str, list[tuple[Path, dict[str, Any]]]] = {}
    for path in sorted(directory.rglob("record.json")):
        record = json.loads(path.read_text(encoding="utf-8"))
        if record.get("validation_version") is not None or not path.with_name("raw_response.json").is_file():
            continue
        if record.get("status") != CollectionStatus.COLLECTED and not (
            record.get("status") == CollectionStatus.FAILED and record.get("error_type") == "ValueError"
        ):
            continue
        candidates.setdefault(record["request_hash"], []).append((path, record))
    if not candidates:
        raise ValueError("No original preserved responses available for batch revalidation")
    excluded_requests = []
    if paired_only:
        paired_hashes = set()
        for path in sorted(directory.rglob("comparisons/*.json")):
            comparison = json.loads(path.read_text(encoding="utf-8"))
            paired_hashes.update((comparison["baseline"]["request_hash"], comparison["candidate"]["request_hash"]))
        excluded_requests = sorted(set(candidates) - paired_hashes)
        candidates = {key: value for key, value in candidates.items() if key in paired_hashes}
        if not candidates:
            raise ValueError("No preserved comparison pairs available for batch revalidation")
    results = []
    completed: dict[str, tuple[Path, Path]] = {}
    for request_hash, runs in sorted(candidates.items()):
        source, original = min(runs, key=lambda item: (item[1].get("created_at", ""), str(item[0])))
        summary = {"source_record": str(source.resolve()), "source_request_hash": request_hash,
                   "prompt_version": original["prompt_version"], "preserved_response_runs": len(runs)}
        try:
            result = revalidate_record(source, output, baseline_profile=baseline_profile)
            _, chunks, record = load_record(result)
            summary.update(status=record["status"], record=str(result.resolve()), indexable_chunks=len(chunks),
                           excluded_chunks=len(record["excluded_chunks"]))
            completed[request_hash] = (source, result)
        except (ValueError, KeyError, OSError, ValidationError) as exception:
            summary.update(status=CollectionStatus.FAILED.value, error_type=type(exception).__name__)
            if isinstance(exception, ValidationError):
                summary.update(validation_path=list(exception.absolute_path), validation_rule=exception.validator)
            else:
                summary["error_message"] = str(exception)
        results.append(summary)
    comparisons = []
    for source, result in completed.values():
        for path in sorted(source.parent.joinpath("comparisons").glob("*.json")):
            previous = json.loads(path.read_text(encoding="utf-8"))
            baseline_hash = previous["baseline"]["request_hash"]
            if baseline_hash in completed:
                baseline = GenerationBaseline.load(completed[baseline_hash][1])
                comparisons.append(str(baseline.write_report(result).resolve()))
    report = {"api_calls": 0, "validation_version": ValidationVersion.SUBJECT_ONLY.value,
              "selection": "earliest_preserved_response_per_request", "records": results, "comparisons": comparisons,
              "paired_only": paired_only, "out_of_scope_request_hashes": excluded_requests,
              "semantic_quality_evaluated": False,
              "failed": sum(item["status"] == CollectionStatus.FAILED for item in results)}
    destination = output / "revalidation-batches" / str(uuid.uuid4()) / "report.json"
    write_json(destination, report)
    return destination
