"""Reuse a validated request for controlled prompt comparisons."""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from app.enrichment.agent import AgentSettings
from app.enrichment.artifacts import write_json
from app.enrichment.contracts import CollectionStatus, fingerprint
from .artifacts import SourceBundle, load_record


@dataclass(frozen=True)
class GenerationBaseline:
    bundle: SourceBundle
    request: dict[str, Any]
    record: dict[str, Any]
    actual_model: str | None
    response_id: str | None

    @classmethod
    def load(cls, path: Path) -> GenerationBaseline:
        bundle, _, record = load_record(path)
        request = json.loads(path.with_name("request.json").read_text(encoding="utf-8"))
        response = json.loads(path.with_name("raw_response.json").read_text(encoding="utf-8"))
        return cls(
            bundle=bundle,
            request=request,
            record=record,
            actual_model=response.get("model"),
            response_id=response.get("id"),
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

    def write_report(self, result_path: Path) -> Path:
        result = json.loads(result_path.read_text(encoding="utf-8"))
        request = json.loads(result_path.with_name("request.json").read_text(encoding="utf-8"))
        self.verify_request(request)
        actual_model = None
        if result["status"] == CollectionStatus.COLLECTED:
            load_record(result_path)
            response = json.loads(result_path.with_name("raw_response.json").read_text(encoding="utf-8"))
            actual_model = response.get("model")
        baseline = {
            "request_hash": self.record["request_hash"],
            "prompt_version": self.record["prompt_version"],
            "actual_model": self.actual_model,
            "response_id": self.response_id,
        }
        model_match = self.actual_model == actual_model if self.actual_model and actual_model else None
        report = {
            "baseline": baseline,
            "candidate": {
                "request_hash": result["request_hash"],
                "prompt_version": result["prompt_version"],
                "status": result["status"],
                "actual_model": actual_model,
            },
            "input_and_settings_match": True,
            "actual_model_match": model_match,
            "semantic_quality_evaluated": False,
        }
        destination = result_path.parent / "comparisons" / f"{fingerprint(baseline)}.json"
        write_json(destination, report)
        return destination
