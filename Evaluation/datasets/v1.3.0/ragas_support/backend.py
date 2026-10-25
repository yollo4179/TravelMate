"""Ragas compatibility and OpenAI wiring, isolated from dataset preparation."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import math
from typing import Any

from .inputs import EvaluationBatch
from .langsmith_observability import evaluation_span
from .settings import EvaluatorSettings, MetricName


def finite_score(value: Any) -> float:
    score = float(value)
    if not math.isfinite(score):
        raise ValueError("Ragas returned a non-finite score; batch was not published")
    return score


class RagasBackend:
    @property
    def version(self) -> str:
        return importlib.metadata.version("ragas")

    def create_client(self, settings: EvaluatorSettings) -> Any:
        from openai import AsyncOpenAI
        from langsmith.wrappers import wrap_openai

        client = AsyncOpenAI(api_key=settings.api_key, base_url="https://api.openai.com/v1")
        return wrap_openai(client)

    async def score_ids(self, batch: EvaluationBatch) -> list[dict[str, Any]]:
        from ragas.dataset_schema import SingleTurnSample
        # ID metrics are not yet in collections in the pinned Ragas 0.4.3.
        from ragas.metrics._context_precision import IDBasedContextPrecision
        from ragas.metrics._context_recall import IDBasedContextRecall

        precision = IDBasedContextPrecision()
        recall = IDBasedContextRecall()
        scored = []
        for version, samples in batch.samples_by_version.items():
            for sample in samples:
                context_sample = SingleTurnSample(
                    retrieved_context_ids=[str(value) for value in sample["retrieved_context_ids"]],
                    reference_context_ids=[str(value) for value in sample["reference_context_ids"]],
                )
                with evaluation_span(
                    operation="ragas.id_based_context_precision",
                    case_id=sample["case_id"],
                    strategy_version=version,
                    metric_name=MetricName.ID_PRECISION.value,
                ) as precision_span:
                    precision_score = finite_score(await precision.single_turn_ascore(context_sample))
                    if precision_span is not None:
                        precision_span.set_attribute("evaluation.score", precision_score)
                with evaluation_span(
                    operation="ragas.id_based_context_recall",
                    case_id=sample["case_id"],
                    strategy_version=version,
                    metric_name=MetricName.ID_RECALL.value,
                ) as recall_span:
                    recall_score = finite_score(await recall.single_turn_ascore(context_sample))
                    if recall_span is not None:
                        recall_span.set_attribute("evaluation.score", recall_score)
                scored.append({
                    **{key: sample[key] for key in (
                        "case_id", "user_input", "retrieved_context_ids", "reference_context_ids",
                        "judged_retrieved_context_ids", "unjudged_retrieved_context_ids",
                    )},
                    "strategy_version": version,
                    "retrieved_context_count": len(sample["retrieved_context_ids"]),
                    "judged_retrieved_context_count": len(sample["judged_retrieved_context_ids"]),
                    "unjudged_retrieved_context_count": len(sample["unjudged_retrieved_context_ids"]),
                    MetricName.ID_PRECISION.value: precision_score,
                    MetricName.ID_RECALL.value: recall_score,
                    "metric_provider": "RAGAS",
                    "metric_source": "IDBasedContextPrecision, IDBasedContextRecall",
                })
        return scored

    async def score_llm(
        self,
        batch: EvaluationBatch,
        settings: EvaluatorSettings,
    ) -> list[dict[str, Any]]:
        from ragas.embeddings.base import embedding_factory
        from ragas.llms import llm_factory
        from ragas.metrics.collections import AnswerCorrectness, ContextRecall, Faithfulness

        async with self.create_client(settings) as client:
            judge = llm_factory(settings.judge_model, provider="openai", client=client)
            embeddings = embedding_factory(
                "openai",
                model=settings.embedding_model,
                client=client,
                interface="modern",
            )
            correctness = AnswerCorrectness(llm=judge, embeddings=embeddings, weights=[0.75, 0.25])
            faithfulness = Faithfulness(llm=judge)
            recall = ContextRecall(llm=judge)
            scored = []
            for version, samples in batch.samples_by_version.items():
                for sample in samples:
                    with evaluation_span(
                        operation="ragas.answer_correctness",
                        case_id=sample["case_id"],
                        strategy_version=version,
                        metric_name=MetricName.ANSWER_CORRECTNESS.value,
                    ) as correctness_span:
                        correctness_result = await correctness.ascore(
                            user_input=sample["user_input"],
                            response=sample["response"],
                            reference=sample["reference"],
                        )
                        if correctness_span is not None:
                            correctness_span.set_attribute("evaluation.score", finite_score(correctness_result.value))
                    with evaluation_span(
                        operation="ragas.faithfulness",
                        case_id=sample["case_id"],
                        strategy_version=version,
                        metric_name=MetricName.FAITHFULNESS.value,
                    ) as faithfulness_span:
                        faithfulness_result = await faithfulness.ascore(
                            user_input=sample["user_input"],
                            response=sample["response"],
                            retrieved_contexts=sample["retrieved_contexts"],
                        )
                        if faithfulness_span is not None:
                            faithfulness_span.set_attribute("evaluation.score", finite_score(faithfulness_result.value))
                    with evaluation_span(
                        operation="ragas.context_recall",
                        case_id=sample["case_id"],
                        strategy_version=version,
                        metric_name=MetricName.CONTEXT_RECALL.value,
                    ) as recall_span:
                        recall_result = await recall.ascore(
                            user_input=sample["user_input"],
                            retrieved_contexts=sample["retrieved_contexts"],
                            reference=sample["reference"],
                        )
                        if recall_span is not None:
                            recall_span.set_attribute("evaluation.score", finite_score(recall_result.value))
                    scored.append({
                        "case_id": sample["case_id"],
                        "strategy_version": version,
                        "user_input": sample["user_input"],
                        "reference": sample["reference"],
                        "response_sha256": hashlib.sha256(sample["response"].encode()).hexdigest(),
                        "retrieved_contexts_sha256": hashlib.sha256(
                            json.dumps(sample["retrieved_contexts"], ensure_ascii=False).encode()
                        ).hexdigest(),
                        MetricName.ANSWER_CORRECTNESS.value: finite_score(correctness_result.value),
                        MetricName.FAITHFULNESS.value: finite_score(faithfulness_result.value),
                        MetricName.CONTEXT_RECALL.value: finite_score(recall_result.value),
                        "metric_provider": "RAGAS",
                        "metric_source": "ragas.metrics.collections: AnswerCorrectness, Faithfulness, ContextRecall",
                        "evaluator": settings.public_settings(),
                        "response_source": "actual API response; not a synthesized guide answer",
                    })
            return scored
