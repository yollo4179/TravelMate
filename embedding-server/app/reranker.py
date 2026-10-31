from __future__ import annotations

import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from datetime import UTC, datetime

import torch
from opentelemetry.trace import Span, get_current_span
from sentence_transformers import CrossEncoder

from app.config import MODEL_DEVICE_RERANKER, MODEL_NAME_RERANKER
from app.device import select_inference_device
from app.reranking.strategies.base import RerankingStrategyType
from app.reranking.strategies.registry import build_reranking_strategy_registry


RERANK_BATCH_SIZE = max(1, int(os.getenv("RERANK_BATCH_SIZE", "32")))
RERANK_DIAGNOSTICS_ENABLED = os.getenv("RERANK_DIAGNOSTICS_ENABLED", "false").lower() == "true"
RERANK_EXECUTION_STRATEGY = os.getenv("RERANK_EXECUTION_STRATEGY")


class Reranker:
    def __init__(self) -> None:
        load_started_at = time.perf_counter()
        device = select_inference_device(MODEL_DEVICE_RERANKER)
        print(f"[Reranker] 모델 로딩 중: {MODEL_NAME_RERANKER} (device={device})")
        try:
            self.model = CrossEncoder(MODEL_NAME_RERANKER, device=device)
        except Exception:
            if device != "cuda":
                raise
            logging.getLogger(__name__).exception(
                "Reranker failed to initialize on CUDA; retrying on CPU"
            )
            device = "cpu"
            self.model = CrossEncoder(MODEL_NAME_RERANKER, device=device)

        self.device = device
        self.model_name = MODEL_NAME_RERANKER
        self.model_load_elapsed_ms = (time.perf_counter() - load_started_at) * 1000
        self.batch_size = RERANK_BATCH_SIZE
        self.strategy_type = self._resolve_strategy_type()
        self.strategy_registry = build_reranking_strategy_registry()
        self.loaded_at = datetime.now(UTC)
        self.loaded_at_monotonic = time.perf_counter()
        self.inference_count = 0
        self.active_calls = 0
        self.active_spans: dict[int, Span] = {}
        self.input_fingerprint_counts: OrderedDict[str, int] = OrderedDict()
        self.state_lock = threading.Lock()
        print(f"[Reranker] 로딩 완료. strategy={self.strategy_type.value}")

    @staticmethod
    def _resolve_strategy_type() -> RerankingStrategyType:
        if RERANK_EXECUTION_STRATEGY:
            return RerankingStrategyType(RERANK_EXECUTION_STRATEGY)
        if RERANK_DIAGNOSTICS_ENABLED:
            return RerankingStrategyType.MANUAL_DIAGNOSTIC
        return RerankingStrategyType.CROSS_ENCODER_PREDICT

    @property
    def execution_mode(self) -> str:
        return self.strategy_type.value

    def batch_count(self, candidate_count: int) -> int:
        return (candidate_count + self.batch_size - 1) // self.batch_size

    def input_token_lengths(self, query: str, texts: list[str]) -> list[int]:
        encoded = self.model.tokenizer(
            [query] * len(texts),
            texts,
            padding=False,
            truncation=True,
            max_length=self.model.max_length,
            return_length=True,
        )
        return encoded["length"]

    def rerank(
        self,
        query: str,
        texts: list[str],
        execution_wait_ms: float = 0.0,
    ) -> list[float]:
        span = get_current_span()
        fingerprint_started_at = time.perf_counter()
        input_fingerprint = self._input_fingerprint(query, texts)
        fingerprint_elapsed_ms = (time.perf_counter() - fingerprint_started_at) * 1000
        inference_index, active_calls, same_input_prior_count = self._begin_call(span, input_fingerprint)
        self._set_common_attributes(
            span,
            query,
            texts,
            inference_index,
            execution_wait_ms,
            active_calls,
            input_fingerprint,
            same_input_prior_count,
            fingerprint_elapsed_ms,
        )

        try:
            strategy = self.strategy_registry.resolve(self.strategy_type)
            scores = strategy.execute(
                self.model,
                query,
                texts,
                self.batch_size,
                span,
            )
            span.set_attribute("reranking.score_count", len(scores))
            if scores:
                span.set_attribute("reranking.score_min", min(scores))
                span.set_attribute("reranking.score_max", max(scores))
            return scores
        finally:
            self._end_call(inference_index)

    def _set_common_attributes(
        self,
        span: Span,
        query: str,
        texts: list[str],
        inference_index: int,
        execution_wait_ms: float,
        active_calls: int,
        input_fingerprint: str,
        same_input_prior_count: int,
        fingerprint_elapsed_ms: float,
    ) -> None:
        span.set_attribute("reranking.query", query)
        span.set_attribute("reranking.model", self.model_name)
        span.set_attribute("reranking.device", self.device)
        span.set_attribute("reranking.batch_size", self.batch_size)
        span.set_attribute("reranking.candidate_count", len(texts))
        span.set_attribute("reranking.batch_count", self.batch_count(len(texts)))
        span.set_attribute("reranking.execution_strategy", self.strategy_type.value)
        span.set_attribute("reranking.execution_wait_ms", execution_wait_ms)
        span.set_attribute("reranking.inference_index_after_model_load", inference_index)
        span.set_attribute("reranking.first_inference_after_model_load", inference_index == 1)
        span.set_attribute("reranking.prior_real_inference_count", max(0, inference_index - 1))
        span.set_attribute("reranking.warmup_request_configured", False)
        span.set_attribute(
            "reranking.warmup_observation",
            "first_after_load" if inference_index == 1 else "prior_real_inference_observed",
        )
        span.set_attribute("reranking.concurrent_calls_at_start", active_calls)
        span.set_attribute("reranking.concurrent_overlap", active_calls > 1)
        span.set_attribute("reranking.input_fingerprint", input_fingerprint)
        span.set_attribute("reranking.same_input_prior_inference_count", same_input_prior_count)
        span.set_attribute("reranking.first_inference_for_input", same_input_prior_count == 0)
        span.set_attribute("reranking.input_fingerprint_elapsed_ms", fingerprint_elapsed_ms)
        span.set_attribute("reranking.model_loaded_at", self.loaded_at.isoformat())
        span.set_attribute("reranking.model_load_elapsed_ms", self.model_load_elapsed_ms)
        span.set_attribute(
            "reranking.diagnostics.process_age_since_model_load_ms",
            (time.perf_counter() - self.loaded_at_monotonic) * 1000,
        )
        span.set_attribute("reranking.query_text_characters", len(query))
        span.set_attribute("reranking.candidate_text_characters", [len(text) for text in texts])
        span.set_attribute("reranking.parameter_dtype", self._parameter_dtype())
        if self.device == "cuda" and torch.cuda.is_available():
            span.set_attribute("reranking.gpu_name", torch.cuda.get_device_name())

    def _begin_call(self, span: Span, input_fingerprint: str) -> tuple[int, int, int]:
        with self.state_lock:
            self.inference_count += 1
            self.active_calls += 1
            inference_index = self.inference_count
            active_calls = self.active_calls
            same_input_prior_count = self.input_fingerprint_counts.get(input_fingerprint, 0)
            self.input_fingerprint_counts[input_fingerprint] = same_input_prior_count + 1
            self.input_fingerprint_counts.move_to_end(input_fingerprint)
            if len(self.input_fingerprint_counts) > 1024:
                self.input_fingerprint_counts.popitem(last=False)
            for active_span in self.active_spans.values():
                active_span.set_attribute("reranking.concurrent_overlap", True)
            self.active_spans[inference_index] = span
            span.set_attribute("reranking.concurrent_max_active_calls", active_calls)
            return inference_index, active_calls, same_input_prior_count

    @staticmethod
    def _input_fingerprint(query: str, texts: list[str]) -> str:
        digest = hashlib.sha256()
        digest.update(query.encode("utf-8"))
        for text in texts:
            digest.update(b"\0")
            digest.update(text.encode("utf-8"))
        return digest.hexdigest()

    def _end_call(self, inference_index: int) -> None:
        with self.state_lock:
            self.active_spans.pop(inference_index, None)
            self.active_calls = max(0, self.active_calls - 1)

    def _parameter_dtype(self) -> str:
        parameter = next(self.model.model.parameters(), None)
        return str(parameter.dtype).removeprefix("torch.") if parameter is not None else "unknown"


reranker = Reranker()
