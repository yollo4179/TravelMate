"""Metric-specific prerequisites and the user-selected all-or-none policy."""
from __future__ import annotations

from typing import Any

from .inputs import EvaluationBatch
from .settings import EvaluatorSettings, LLM_METRICS, MetricName, RunStatus


def build_precheck(batch: EvaluationBatch, settings: EvaluatorSettings) -> dict[str, Any]:
    samples = [sample for rows in batch.samples_by_version.values() for sample in rows]
    metrics: dict[str, dict[str, Any]] = {}
    for metric in LLM_METRICS:
        reference_required = metric != MetricName.FAITHFULNESS
        response_required = metric != MetricName.CONTEXT_RECALL
        contexts_required = metric != MetricName.ANSWER_CORRECTNESS
        embedding_required = metric == MetricName.ANSWER_CORRECTNESS
        missing_reference = sorted({sample["case_id"] for sample in samples if reference_required and not sample["reference"]})
        missing_response = sorted({sample["case_id"] for sample in samples if response_required and not (sample["response"] or "").strip()})
        missing_contexts = sorted({sample["case_id"] for sample in samples if contexts_required and not any(text.strip() for text in sample["retrieved_contexts"])})
        reasons = []
        if not samples:
            reasons.append("no_completed_paired_cases")
        if missing_reference:
            reasons.append("missing_reference")
        if missing_response:
            reasons.append("missing_response")
        if missing_contexts:
            reasons.append("missing_retrieved_contexts")
        if not settings.judge_configured:
            reasons.append("llm_evaluator_not_configured")
        if embedding_required and not settings.embeddings_configured:
            reasons.append("embedding_evaluator_not_configured")
        metrics[metric.value] = {
            "status": RunStatus.BLOCKED.value if reasons else RunStatus.READY.value,
            "reference_required": reference_required,
            "response_required": response_required,
            "retrieved_contexts_required": contexts_required,
            "embeddings_required": embedding_required,
            "missing_reference_case_ids": missing_reference,
            "missing_response_case_ids": missing_response,
            "missing_retrieved_context_case_ids": missing_contexts,
            "llm_evaluator_configured": settings.judge_configured,
            "embeddings_configured": settings.embeddings_configured if embedding_required else None,
            "reasons": reasons,
        }
    ready = all(not entry["reasons"] for entry in metrics.values())
    for entry in metrics.values():
        entry["deferred_by_batch_policy"] = not ready
    return {
        "status": RunStatus.READY.value if ready else RunStatus.BLOCKED.value,
        "execution_policy": {"mode": "all_or_none", "scope": "all three LLM metrics across completed paired cases and both versions"},
        "requested_metrics": [metric.value for metric in LLM_METRICS],
        "paired_case_count": batch.paired_case_count,
        "metrics": metrics,
        "score_count": 0,
        "source_missing_reference_case_ids": batch.missing_reference_case_ids,
        "evaluator": settings.public_settings(),
        "llm_connection_verified": False,
        "note": "Configuration presence is not a connectivity check. Faithfulness does not require reference. No expected answer or system output is synthesized.",
    }
