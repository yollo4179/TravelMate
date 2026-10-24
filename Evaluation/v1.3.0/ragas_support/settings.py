"""Explicit evaluator settings; credentials never enter serialized reports."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Mapping


class MetricName(str, Enum):
    ID_PRECISION = "id_based_context_precision"
    ID_RECALL = "id_based_context_recall"
    ANSWER_CORRECTNESS = "answer_correctness"
    FAITHFULNESS = "faithfulness"
    CONTEXT_RECALL = "context_recall"


ID_METRICS = (MetricName.ID_PRECISION, MetricName.ID_RECALL)
LLM_METRICS = (
    MetricName.ANSWER_CORRECTNESS,
    MetricName.FAITHFULNESS,
    MetricName.CONTEXT_RECALL,
)


class RunMode(str, Enum):
    ALL = "all"
    ID = "id"
    LLM = "llm"
    JUDGE = "judge"


class RunStatus(str, Enum):
    READY = "ready"
    BLOCKED = "not_run_batch_prerequisites_incomplete"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True)
class EvaluatorSettings:
    judge_model: str
    embedding_model: str
    api_key: str = field(repr=False)

    @classmethod
    def load(cls, path: Path, environment: Mapping[str, str]) -> EvaluatorSettings:
        configured = json.loads(path.read_text(encoding="utf-8-sig")) if path.exists() else {}
        judge_model = environment.get("RAGAS_JUDGE_MODEL", configured.get("judge_model", ""))
        embedding_model = environment.get("RAGAS_EMBEDDING_MODEL", configured.get("embedding_model", ""))
        if not isinstance(judge_model, str) or not isinstance(embedding_model, str):
            raise ValueError("Evaluator model names must be strings")
        return cls(
            judge_model=judge_model.strip(),
            embedding_model=embedding_model.strip(),
            api_key=environment.get("OPENAI_API_KEY", "").strip(),
        )

    @property
    def judge_configured(self) -> bool:
        return bool(self.judge_model and self.api_key)

    @property
    def embeddings_configured(self) -> bool:
        return bool(self.embedding_model and self.api_key)

    def public_settings(self) -> dict[str, object]:
        return {
            "provider": "openai",
            "judge_model": self.judge_model,
            "embedding_model": self.embedding_model,
            "api_key_present": bool(self.api_key),
            "answer_correctness_weights": [0.75, 0.25],
            "configuration_present_is_not_connection_verification": True,
        }
