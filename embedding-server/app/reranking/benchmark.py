from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import statistics
import time
from typing import Any
from pathlib import Path

import asyncpg
import numpy as np
import torch
from opentelemetry.trace import Span

from app.embedder import embedder
from app.observability import tracer
from app.reranker import RERANK_BATCH_SIZE, reranker
from app.reranking.strategies.base import RerankingStrategy, RerankingStrategyType
from app.reranking.strategies.registry import build_reranking_strategy_registry


DEFAULT_QUERY = "서울 카페"
RETRIEVE_TOP_K = 30
WARMUP_RUNS = 2
MEASURED_RUNS = 5


def synchronize_device() -> None:
    if reranker.device == "cuda" and torch.cuda.is_available():
        torch.cuda.synchronize(torch.device(reranker.device))


async def retrieve_fixed_candidates(query: str) -> list[dict[str, Any]]:
    database_url = os.environ["DATABASE_URL"]
    query_vector = embedder.embed([query])[0]
    vector_parameter = "[" + ",".join(map(str, query_vector)) + "]"
    async with asyncpg.create_pool(dsn=database_url, min_size=1, max_size=1) as pool:
        async with pool.acquire() as connection:
            rows = await connection.fetch(
                """
                SELECT place_id, name, description,
                       1 - (embedding <=> $1::vector) AS semantic_score
                FROM place_embeddings
                WHERE document_status = 'READY'
                  AND embedding IS NOT NULL
                  AND 1 - (embedding <=> $1::vector) >= 0
                ORDER BY embedding <=> $1::vector
                LIMIT $2
                """,
                vector_parameter,
                RETRIEVE_TOP_K,
            )
    return [dict(row) for row in rows]


def score_candidates(
    strategy: RerankingStrategy,
    query: str,
    texts: list[str],
    span: Span,
) -> list[float]:
    return strategy.execute(
        reranker.model,
        query,
        texts,
        RERANK_BATCH_SIZE,
        span,
    )


def timed_run(strategy: RerankingStrategy, query: str, texts: list[str]) -> tuple[list[float], float]:
    with tracer().start_as_current_span("reranking.benchmark") as span:
        started_at = time.perf_counter()
        scores = score_candidates(strategy, query, texts, span)
        synchronize_device()
        elapsed_ms = (time.perf_counter() - started_at) * 1000
    return scores, elapsed_ms


def capture_forward_inputs(
    strategy: RerankingStrategy,
    query: str,
    texts: list[str],
) -> tuple[list[float], dict[str, Any]]:
    batches: list[dict[str, Any]] = []
    original_preprocess = reranker.model.preprocess

    def capture_preprocess(
        inputs: Any,
        *arguments: Any,
        **keyword_arguments: Any,
    ) -> dict[str, torch.Tensor]:
        features = original_preprocess(inputs, *arguments, **keyword_arguments)
        tensor_features = {
            name: tensor
            for name, tensor in features.items()
            if isinstance(tensor, torch.Tensor)
        }
        input_ids = tensor_features.get("input_ids")
        attention_mask = tensor_features.get("attention_mask")
        token_type_ids = tensor_features.get("token_type_ids")
        batches.append(
            {
                "shape": list(input_ids.shape) if input_ids is not None else [],
                "input_ids_sha256": _tensor_fingerprint(input_ids),
                "attention_mask_sha256": _tensor_fingerprint(attention_mask),
                "token_type_ids_sha256": _tensor_fingerprint(token_type_ids),
                "actual_sequence_lengths": (
                    [int(length) for length in attention_mask.sum(dim=1).tolist()]
                    if attention_mask is not None
                    else []
                ),
                "padded_sequence_length": int(input_ids.shape[1])
                if input_ids is not None and input_ids.ndim > 1
                else 0,
                "feature_dtypes": {
                    name: str(tensor.dtype).removeprefix("torch.")
                    for name, tensor in tensor_features.items()
                },
            }
        )
        return features

    reranker.model.preprocess = capture_preprocess
    try:
        scores, _ = timed_run(strategy, query, texts)
    finally:
        del reranker.model.preprocess

    return scores, {"batches": batches}


def _tensor_fingerprint(tensor: torch.Tensor | None) -> str | None:
    if tensor is None:
        return None
    tensor_bytes = tensor.detach().to("cpu").contiguous().numpy().tobytes()
    return hashlib.sha256(tensor_bytes).hexdigest()


def _ranked_indices(scores: list[float]) -> list[int]:
    return list(np.argsort(-np.asarray(scores, dtype=np.float64)))


def _rank_equivalence(reference_scores: list[float], compared_scores: list[float]) -> dict[str, Any]:
    reference = np.asarray(reference_scores, dtype=np.float64)
    compared = np.asarray(compared_scores, dtype=np.float64)
    reference_order = _ranked_indices(reference_scores)
    compared_order = _ranked_indices(compared_scores)
    score_differences = np.abs(reference - compared)
    top_k = min(10, len(reference_order))
    return {
        "scores_exactly_equal": bool(np.array_equal(reference, compared)),
        "max_absolute_score_delta": float(score_differences.max()) if len(score_differences) else 0.0,
        "mean_absolute_score_delta": float(score_differences.mean()) if len(score_differences) else 0.0,
        "rank_order_exactly_equal": reference_order == compared_order,
        "top_10_overlap": (
            len(set(reference_order[:top_k]) & set(compared_order[:top_k])) / top_k
            if top_k
            else 1.0
        ),
        "ranking_quality_preserved_for_fixed_judgments": reference_order == compared_order,
    }


def _summarize_times(samples: list[float]) -> dict[str, float]:
    return {
        "runs": len(samples),
        "median_ms": statistics.median(samples),
        "mean_ms": statistics.fmean(samples),
        "min_ms": min(samples),
        "max_ms": max(samples),
        "p95_ms": float(np.percentile(samples, 95)),
    }


def _configured_sequence_limit() -> int | None:
    transformer = reranker.model[0]
    sequence_limit = getattr(transformer, "max_seq_length", None)
    if isinstance(sequence_limit, int):
        return sequence_limit
    tokenizer = getattr(transformer, "tokenizer", None)
    tokenizer_limit = getattr(tokenizer, "model_max_length", None)
    return tokenizer_limit if isinstance(tokenizer_limit, int) and tokenizer_limit < 1_000_000 else None


def _raw_token_lengths(query: str, texts: list[str]) -> list[int]:
    tokenizer = reranker.model[0].tokenizer
    return [
        len(tokenizer(query, text, add_special_tokens=True, truncation=False)["input_ids"])
        for text in texts
    ]


def _token_comparison(
    query: str,
    texts: list[str],
    captured_inputs: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    strategy_names = list(captured_inputs)
    reference_name = strategy_names[0]
    reference_batches = captured_inputs[reference_name]["batches"]
    raw_token_lengths = _raw_token_lengths(query, texts)
    sorted_indices = np.argsort([-(len(query) + len(text)) for text in texts])
    if reranker.model._can_flatten_inputs():
        sorted_indices = reranker.model._interleave_sorted_indices(sorted_indices)
    ordered_raw_token_lengths = [raw_token_lengths[index] for index in sorted_indices]
    per_strategy = {
        name: {
            "captured_pair_count": sum(
                len(batch["actual_sequence_lengths"])
                for batch in result["batches"]
            ),
            "raw_pair_count": len(raw_token_lengths),
            "truncated_pair_count": (
                sum(
                    raw_length > actual_length
                    for raw_length, actual_length in zip(
                        ordered_raw_token_lengths,
                        [
                            length
                            for batch in result["batches"]
                            for length in batch["actual_sequence_lengths"]
                        ],
                        strict=True,
                    )
                )
                if sum(
                    len(batch["actual_sequence_lengths"])
                    for batch in result["batches"]
                ) == len(raw_token_lengths)
                else None
            ),
            "batch_count": len(result["batches"]),
            "batch_sizes": [batch["shape"][0] for batch in result["batches"]],
            "padded_sequence_lengths": [batch["padded_sequence_length"] for batch in result["batches"]],
            "actual_sequence_lengths": [
                length
                for batch in result["batches"]
                for length in batch["actual_sequence_lengths"]
            ],
            "input_id_hashes": [batch["input_ids_sha256"] for batch in result["batches"]],
            "attention_mask_hashes": [batch["attention_mask_sha256"] for batch in result["batches"]],
            "token_type_id_hashes": [batch["token_type_ids_sha256"] for batch in result["batches"]],
            "tensor_dtypes": [batch["feature_dtypes"] for batch in result["batches"]],
        }
        for name, result in captured_inputs.items()
    }
    return {
        "configured_max_sequence_length": _configured_sequence_limit(),
        "raw_untruncated_token_lengths": raw_token_lengths,
        "actual_model_inputs_by_strategy": per_strategy,
        "model_inputs_identical_to_original_predict": {
            strategy_name: result["batches"] == reference_batches
            for strategy_name, result in captured_inputs.items()
            if strategy_name != reference_name
        },
    }


async def run_benchmark(query: str, warmup_runs: int, measured_runs: int) -> dict[str, Any]:
    candidates = await retrieve_fixed_candidates(query)
    if not candidates:
        raise RuntimeError("The fixed query did not return any candidates")

    texts = [candidate["description"] or candidate["name"] for candidate in candidates]
    registry = build_reranking_strategy_registry()
    strategy_types = [
        RerankingStrategyType.CROSS_ENCODER_PREDICT,
        RerankingStrategyType.INSTRUMENTED_PREDICT,
        RerankingStrategyType.AUTOCAST_FP16,
        RerankingStrategyType.MANUAL_DIAGNOSTIC,
    ]
    strategies = [registry.resolve(strategy_type) for strategy_type in strategy_types]

    for strategy in strategies:
        for _ in range(warmup_runs):
            timed_run(strategy, query, texts)

    timing_samples = {strategy.strategy_type.value: [] for strategy in strategies}
    final_scores: dict[str, list[float]] = {}
    for _ in range(measured_runs):
        for strategy in strategies:
            scores, elapsed_ms = timed_run(strategy, query, texts)
            timing_samples[strategy.strategy_type.value].append(elapsed_ms)
            final_scores[strategy.strategy_type.value] = scores

    captured_inputs: dict[str, dict[str, Any]] = {}
    captured_scores: dict[str, list[float]] = {}
    for strategy in (strategies[0], strategies[2], strategies[3]):
        scores, input_signature = capture_forward_inputs(strategy, query, texts)
        captured_scores[strategy.strategy_type.value] = scores
        captured_inputs[strategy.strategy_type.value] = input_signature

    reference_strategy = strategies[0].strategy_type.value
    reference_scores = final_scores[reference_strategy]
    equivalence = {
        strategy_name: _rank_equivalence(reference_scores, scores)
        for strategy_name, scores in final_scores.items()
        if strategy_name != reference_strategy
    }
    input_comparison = _token_comparison(query, texts, captured_inputs)
    captured_equivalence = {
        strategy_name: _rank_equivalence(captured_scores[reference_strategy], scores)
        for strategy_name, scores in captured_scores.items()
        if strategy_name != reference_strategy
    }
    baseline_median_ms = timing_samples[reference_strategy]
    baseline_median_ms = statistics.median(baseline_median_ms)
    return {
        "query": query,
        "query_embedding_device": embedder.device,
        "candidate_count": len(candidates),
        "candidate_place_ids_in_semantic_order": [candidate["place_id"] for candidate in candidates],
        "candidate_text_fingerprint": reranker._input_fingerprint(query, texts),
        "candidate_text_characters": [len(text) for text in texts],
        "model": reranker.model_name,
        "device": reranker.device,
        "gpu_name": torch.cuda.get_device_name() if reranker.device == "cuda" and torch.cuda.is_available() else None,
        "parameter_dtype": reranker._parameter_dtype(),
        "batch_size": RERANK_BATCH_SIZE,
        "warmup_runs_per_strategy": warmup_runs,
        "measured_runs_per_strategy": measured_runs,
        "timings": {
            strategy_name: {
                **_summarize_times(samples),
                "speedup_vs_original_predict": (
                    baseline_median_ms / statistics.median(samples)
                    if statistics.median(samples)
                    else 0.0
                ),
            }
            for strategy_name, samples in timing_samples.items()
        },
        "tokenization_comparison": input_comparison,
        "score_and_rank_comparison_to_original_predict": equivalence,
        "captured_run_output_comparison_to_original_predict": captured_equivalence,
        "execution_differences": {
            strategies[0].strategy_type.value: "Direct CrossEncoder.predict(pairs) call with library defaults; no explicit synchronization added by the strategy.",
            strategies[1].strategy_type.value: "Same CrossEncoder.predict(pairs) call, with CUDA synchronization before and after for an isolated wall-time measurement.",
            strategies[2].strategy_type.value: "Original CrossEncoder.predict(pairs) under CUDA float16 autocast; experimental optimization candidate.",
            strategies[3].strategy_type.value: "Manual batching, preprocessing, device transfer, forward, activation, and original-order restoration; CUDA synchronization and events split the stages.",
        },
        "ranked_place_ids": {
            strategy_name: [
                candidates[index]["place_id"]
                for index in _ranked_indices(scores)
            ]
            for strategy_name, scores in captured_scores.items()
        },
        "relevance_metrics": {
            "status": "not_calculated",
            "reason": "No human relevance judgments were provided for this exact query and candidate set.",
            "quality_preservation_check": "Exact rank parity implies identical deterministic ranking metrics for any fixed relevance labels.",
        },
    }


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare reranking strategies on one fixed candidate set.")
    parser.add_argument("--query", default=DEFAULT_QUERY)
    parser.add_argument("--warmups", type=int, default=WARMUP_RUNS)
    parser.add_argument("--runs", type=int, default=MEASURED_RUNS)
    parser.add_argument("--output", type=Path)
    return parser.parse_args()


def main() -> None:
    arguments = parse_arguments()
    result = asyncio.run(run_benchmark(arguments.query, arguments.warmups, arguments.runs))
    serialized_result = json.dumps(result, ensure_ascii=False, indent=2)
    if arguments.output is None:
        print(serialized_result)
        return
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(serialized_result + "\n", encoding="utf-8")
    print(f"Benchmark report written to {arguments.output}")


if __name__ == "__main__":
    main()
