from __future__ import annotations

import time

import torch
from opentelemetry.trace import Span
from sentence_transformers import CrossEncoder

from app.reranking.strategies.base import RerankingStrategy, RerankingStrategyType


class CrossEncoderPredictStrategy(RerankingStrategy):
    strategy_type = RerankingStrategyType.CROSS_ENCODER_PREDICT

    def execute(
        self,
        model: CrossEncoder,
        query: str,
        texts: list[str],
        batch_size: int,
        span: Span,
    ) -> list[float]:
        del batch_size
        pairs = [[query, text] for text in texts]
        started_at = time.perf_counter()
        scores = model.predict(pairs)
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        span.set_attribute("reranking.execution_mode", self.strategy_type.value)
        span.set_attribute("reranking.predict_wall_ms", elapsed_ms)
        return scores.tolist()


class InstrumentedCrossEncoderPredictStrategy(RerankingStrategy):
    strategy_type = RerankingStrategyType.INSTRUMENTED_PREDICT

    def execute(
        self,
        model: CrossEncoder,
        query: str,
        texts: list[str],
        batch_size: int,
        span: Span,
    ) -> list[float]:
        del batch_size
        pairs = [[query, text] for text in texts]
        use_cuda = str(model.device).startswith("cuda") and torch.cuda.is_available()
        device = torch.device(model.device)
        sync_count = 0
        if use_cuda:
            torch.cuda.synchronize(device)
            sync_count += 1
        started_at = time.perf_counter()
        scores = model.predict(pairs)
        if use_cuda:
            torch.cuda.synchronize(device)
            sync_count += 1
        elapsed_ms = (time.perf_counter() - started_at) * 1000
        span.set_attribute("reranking.execution_mode", self.strategy_type.value)
        span.set_attribute("reranking.predict_wall_ms", elapsed_ms)
        span.set_attribute("reranking.diagnostics.explicit_cuda_sync_count", sync_count)
        return scores.tolist()
