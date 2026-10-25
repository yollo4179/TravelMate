from __future__ import annotations

import time

import numpy as np
import torch
from opentelemetry.trace import Span
from sentence_transformers import CrossEncoder
from sentence_transformers.util import batch_to_device

from app.observability import tracer
from app.reranking.strategies.base import RerankingStrategy, RerankingStrategyType


class ManualDiagnosticStrategy(RerankingStrategy):
    strategy_type = RerankingStrategyType.MANUAL_DIAGNOSTIC

    @torch.inference_mode()
    def execute(
        self,
        model: CrossEncoder,
        query: str,
        texts: list[str],
        batch_size: int,
        span: Span,
    ) -> list[float]:
        pairs = [[query, text] for text in texts]
        device = model._resolve_inference_device(None)
        is_cuda = device.type == "cuda" and torch.cuda.is_available()
        inference_started_at = time.perf_counter()
        span.set_attribute("reranking.execution_mode", self.strategy_type.value)
        span.set_attribute("reranking.diagnostics.sync_enabled", is_cuda)
        self._set_memory_attributes(span, "before", device if is_cuda else None)

        tokenization_started_at = time.perf_counter()
        model.eval()
        token_lengths = [int(model._input_length(pair)) for pair in pairs]
        sorted_indices = np.argsort([-length for length in token_lengths])
        if model._can_flatten_inputs():
            sorted_indices = model._interleave_sorted_indices(sorted_indices)
        sorted_pairs = [pairs[index] for index in sorted_indices]
        prompt = model._resolve_prompt(None, None)
        batches = [
            sorted_pairs[index : index + batch_size]
            for index in range(0, len(sorted_pairs), batch_size)
        ]

        tokenized_batches: list[dict[str, torch.Tensor]] = []
        batch_sizes: list[int] = []
        input_char_lengths: list[int] = []
        actual_token_lengths: list[int] = []
        padded_batch_lengths: list[int] = []
        with tracer().start_as_current_span("reranking.tokenize") as tokenize_span:
            transformer = model[0]
            configured_max_sequence_length = getattr(transformer, "max_seq_length", None)
            if isinstance(configured_max_sequence_length, int):
                tokenize_span.set_attribute(
                    "reranking.tokenize.configured_max_sequence_length",
                    configured_max_sequence_length,
                )
            for batch in batches:
                batch_sizes.append(len(batch))
                features = model.preprocess(batch, prompt=prompt)
                attention_mask = features.get("attention_mask")
                if attention_mask is not None:
                    actual_token_lengths.extend(
                        int(length) for length in attention_mask.sum(dim=1).tolist()
                    )
                input_ids = features.get("input_ids")
                if input_ids is not None and input_ids.ndim > 1:
                    padded_batch_lengths.append(int(input_ids.shape[1]))
                tokenized_batches.append(features)

            input_char_lengths = token_lengths
            tokenization_ms = (time.perf_counter() - tokenization_started_at) * 1000
            tokenize_span.set_attribute("reranking.tokenize.elapsed_ms", tokenization_ms)
            tokenize_span.set_attribute("reranking.tokenize.batch_count", len(batches))
            tokenize_span.set_attribute("reranking.tokenize.batch_sizes", batch_sizes)
            tokenize_span.set_attribute("reranking.tokenize.input_char_lengths", input_char_lengths)
            tokenize_span.set_attribute(
                "reranking.tokenize.input_char_length_p50",
                self._percentile(input_char_lengths, 50),
            )
            tokenize_span.set_attribute(
                "reranking.tokenize.input_char_length_p95",
                self._percentile(input_char_lengths, 95),
            )
            tokenize_span.set_attribute("reranking.tokenize.input_char_length_max", max(input_char_lengths, default=0))
            tokenize_span.set_attribute("reranking.tokenize.actual_tokens", actual_token_lengths)
            tokenize_span.set_attribute(
                "reranking.tokenize.actual_tokens_p50",
                self._percentile(actual_token_lengths, 50),
            )
            tokenize_span.set_attribute(
                "reranking.tokenize.actual_tokens_p95",
                self._percentile(actual_token_lengths, 95),
            )
            tokenize_span.set_attribute("reranking.tokenize.padded_lengths", padded_batch_lengths)
            token_count_without_padding = sum(actual_token_lengths)
            token_count_with_padding = sum(
                padded_length * batch_size
                for padded_length, batch_size in zip(padded_batch_lengths, batch_sizes, strict=True)
            )
            padding_ratio = (
                token_count_with_padding / token_count_without_padding - 1
                if token_count_without_padding
                else 0.0
            )
            tokenize_span.set_attribute("reranking.tokenize.padding_ratio", padding_ratio)

        transfer_call_ms = 0.0
        transfer_completion_wait_ms = 0.0
        pre_transfer_sync_wait_ms = 0.0
        explicit_sync_count = 0
        transferred_batches: list[dict[str, torch.Tensor]] = []
        with tracer().start_as_current_span("reranking.gpu_transfer") as transfer_span:
            for features in tokenized_batches:
                if is_cuda:
                    sync_started_at = time.perf_counter()
                    torch.cuda.synchronize(device)
                    explicit_sync_count += 1
                    pre_transfer_sync_wait_ms += (time.perf_counter() - sync_started_at) * 1000
                transfer_started_at = time.perf_counter()
                transferred = batch_to_device(features, device)
                transfer_call_ms += (time.perf_counter() - transfer_started_at) * 1000
                if is_cuda:
                    sync_started_at = time.perf_counter()
                    torch.cuda.synchronize(device)
                    explicit_sync_count += 1
                    transfer_completion_wait_ms += (time.perf_counter() - sync_started_at) * 1000
                transferred_batches.append(transferred)
            transfer_ms = transfer_call_ms + transfer_completion_wait_ms
            transfer_span.set_attribute("reranking.gpu_transfer.elapsed_ms", transfer_ms)
            transfer_span.set_attribute("reranking.gpu_transfer.call_wall_ms", transfer_call_ms)
            transfer_span.set_attribute("reranking.gpu_transfer.pre_sync_wait_ms", pre_transfer_sync_wait_ms)
            transfer_span.set_attribute("reranking.gpu_transfer.completion_wait_ms", transfer_completion_wait_ms)
            transfer_span.set_attribute("reranking.gpu_transfer.batch_count", len(transferred_batches))

        forward_call_wall_ms = 0.0
        forward_cuda_event_ms = 0.0
        pre_forward_sync_wait_ms = 0.0
        forward_completion_wait_ms = 0.0
        scores_by_sorted_index: list[torch.Tensor] = []
        with tracer().start_as_current_span("reranking.model_forward") as forward_span:
            for features in transferred_batches:
                if is_cuda:
                    sync_started_at = time.perf_counter()
                    torch.cuda.synchronize(device)
                    explicit_sync_count += 1
                    pre_forward_sync_wait_ms += (time.perf_counter() - sync_started_at) * 1000
                    start_event = torch.cuda.Event(enable_timing=True)
                    end_event = torch.cuda.Event(enable_timing=True)
                    cuda_stream = torch.cuda.current_stream(device)
                    start_event.record(cuda_stream)
                forward_started_at = time.perf_counter()
                output_features = model(features)
                forward_call_wall_ms += (time.perf_counter() - forward_started_at) * 1000
                if is_cuda:
                    end_event.record(cuda_stream)
                    sync_started_at = time.perf_counter()
                    torch.cuda.synchronize(device)
                    explicit_sync_count += 1
                    forward_completion_wait_ms += (time.perf_counter() - sync_started_at) * 1000
                    forward_cuda_event_ms += start_event.elapsed_time(end_event)
                scores = output_features["scores"]
                if torch.is_floating_point(scores) and torch.finfo(scores.dtype).bits < 32:
                    scores = scores.float()
                scores_by_sorted_index.extend(scores)
            forward_span.set_attribute("reranking.model_forward.call_wall_ms", forward_call_wall_ms)
            forward_span.set_attribute("reranking.model_forward.cuda_event_ms", forward_cuda_event_ms)
            forward_span.set_attribute("reranking.model_forward.pre_sync_wait_ms", pre_forward_sync_wait_ms)
            forward_span.set_attribute("reranking.model_forward.completion_wait_ms", forward_completion_wait_ms)
            forward_span.set_attribute("reranking.model_forward.batch_count", len(transferred_batches))

        output_started_at = time.perf_counter()
        with tracer().start_as_current_span("reranking.output") as output_span:
            activated_scores = (
                [model.activation_fn(score) for score in scores_by_sorted_index]
                if model.activation_fn is not None
                else scores_by_sorted_index
            )
            if model.num_labels == 1:
                activated_scores = [score.squeeze(-1) if score.ndim > 0 else score for score in activated_scores]
            original_order = np.argsort(sorted_indices)
            ordered_scores = [activated_scores[index] for index in original_order]
            score_tensor = torch.stack(ordered_scores) if ordered_scores else torch.tensor([], device=device)
            score_values = score_tensor.float().cpu().numpy().tolist() if len(score_tensor) else []
            output_ms = (time.perf_counter() - output_started_at) * 1000
            output_span.set_attribute("reranking.output.elapsed_ms", output_ms)
            output_span.set_attribute("reranking.output.score_count", len(score_values))

        span.set_attribute("reranking.tokenize.elapsed_ms", tokenization_ms)
        span.set_attribute("reranking.tokenize.padding_ratio", padding_ratio)
        span.set_attribute("reranking.gpu_transfer.elapsed_ms", transfer_ms)
        span.set_attribute("reranking.gpu_transfer.call_wall_ms", transfer_call_ms)
        span.set_attribute("reranking.gpu_transfer.pre_sync_wait_ms", pre_transfer_sync_wait_ms)
        span.set_attribute("reranking.gpu_transfer.completion_wait_ms", transfer_completion_wait_ms)
        span.set_attribute("reranking.model_forward.call_wall_ms", forward_call_wall_ms)
        span.set_attribute("reranking.model_forward.cuda_event_ms", forward_cuda_event_ms)
        span.set_attribute("reranking.model_forward.pre_sync_wait_ms", pre_forward_sync_wait_ms)
        span.set_attribute("reranking.model_forward.completion_wait_ms", forward_completion_wait_ms)
        span.set_attribute("reranking.diagnostics.explicit_cuda_sync_count", explicit_sync_count)
        span.set_attribute("reranking.output.elapsed_ms", output_ms)
        span.set_attribute(
            "reranking.diagnostics.observed_total_ms",
            (time.perf_counter() - inference_started_at) * 1000,
        )
        self._set_memory_attributes(span, "after", device if is_cuda else None)
        return score_values

    @staticmethod
    def _percentile(values: list[int], percentile: int) -> int:
        if not values:
            return 0
        ordered_values = sorted(values)
        index = max(0, min(len(ordered_values) - 1, int(np.ceil(percentile / 100 * len(ordered_values))) - 1))
        return ordered_values[index]

    @staticmethod
    def _set_memory_attributes(span: Span, phase: str, device: torch.device | None) -> None:
        if device is None:
            return
        device_index = device.index if device.index is not None else torch.cuda.current_device()
        memory_metrics = {
            "device_index": device_index,
            "allocated_bytes": torch.cuda.memory_allocated(device_index),
            "reserved_bytes": torch.cuda.memory_reserved(device_index),
            "process_peak_allocated_bytes": torch.cuda.max_memory_allocated(device_index),
            "process_peak_reserved_bytes": torch.cuda.max_memory_reserved(device_index),
        }
        for metric_name, metric_value in memory_metrics.items():
            span.set_attribute(f"reranking.diagnostics.memory_{phase}_{metric_name}", metric_value)
