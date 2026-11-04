"""Compare registered GPU reranking strategies on frozen judged candidates."""
from __future__ import annotations

import argparse
import asyncio
from collections import defaultdict
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
import hashlib
import math
import os
from pathlib import Path
import statistics
import sys
import time
from typing import Any, Iterator

import asyncpg
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path.cwd()))
from common.dataset.io import canonical_digest, digest, read_jsonl, write_json, write_jsonl
from common.metrics.ranking import ranking_metrics
from app.embedder import embedder
from app.observability import configure_tracing, tracer
from app.reranker import reranker
from app.reranking.strategies.base import RerankingStrategyType


class ExperimentPhase(StrEnum):
    SCREENING = "screening"
    CONFIRMATION = "confirmation"


@dataclass(frozen=True)
class BatchSetting:
    strategy: RerankingStrategyType
    batch_size: int

    @property
    def name(self) -> str:
        return f"{self.strategy.value}_batch_{self.batch_size}"


BASELINE = BatchSetting(RerankingStrategyType.CROSS_ENCODER_PREDICT, 32)
SETTINGS = tuple(
    BatchSetting(strategy, batch_size)
    for strategy in (RerankingStrategyType.CROSS_ENCODER_PREDICT, RerankingStrategyType.AUTOCAST_FP16)
    for batch_size in (8, 16, 32)
)


def latency_statistics(elapsed_values: list[float]) -> dict[str, float]:
    return {
        "mean_ms": statistics.fmean(elapsed_values),
        "p50_ms": float(np.percentile(elapsed_values, 50)),
        "p95_ms": float(np.percentile(elapsed_values, 95)),
        "max_ms": max(elapsed_values),
    }


class FixedCandidateCollector:
    async def collect(
        self,
        cases: list[dict[str, Any]],
        output: Path,
    ) -> list[dict[str, Any]]:
        frozen_queries: list[dict[str, Any]] = []
        async with asyncpg.create_pool(dsn=os.environ["DATABASE_URL"], min_size=1, max_size=1) as pool:
            for case in cases:
                query = case["input"]["query"]
                conditions = case["input"]["conditions"]
                embedding_started = time.perf_counter()
                embedding = (await asyncio.to_thread(embedder.embed, [query]))[0]
                embedding_ms = (time.perf_counter() - embedding_started) * 1000
                parameters: list[Any] = ["[" + ",".join(map(str, embedding)) + "]"]
                predicates = ["document_status = 'READY'", "embedding IS NOT NULL", "1 - (embedding <=> $1::vector) >= 0"]
                for column in ("region", "city", "category"):
                    if conditions.get(column):
                        parameters.append(conditions[column])
                        predicates.append(f"{column} = ${len(parameters)}")
                sql = f"""
                    SELECT place_id, name, description, 1 - (embedding <=> $1::vector) AS semantic_score
                    FROM place_embeddings
                    WHERE {' AND '.join(predicates)}
                    ORDER BY embedding <=> $1::vector LIMIT 30
                """
                retrieval_started = time.perf_counter()
                candidates = await pool.fetch(sql, *parameters)
                retrieval_ms = (time.perf_counter() - retrieval_started) * 1000
                if not candidates:
                    raise RuntimeError(f"No candidates for {case['case_id']}")
                candidate_ids = [row["place_id"] for row in candidates]
                texts = [row["description"] or row["name"] for row in candidates]
                frozen = {
                    "case_id": case["case_id"],
                    "query": query,
                    "conditions": conditions,
                    "candidate_ids": candidate_ids,
                    "candidate_names": [row["name"] for row in candidates],
                    "texts": texts,
                    "judgments": {str(item["place_id"]): item["relevance"] for item in case["place_judgments"]},
                    "embedding_ms": embedding_ms,
                    "retrieval_ms": retrieval_ms,
                    "candidate_fingerprint": canonical_digest({"query": query, "ids": candidate_ids, "texts": texts}),
                }
                frozen_queries.append(frozen)
                write_jsonl(output / "frozen_candidates.jsonl", frozen_queries)
                print(f"freeze: {case['case_id']} ({len(frozen_queries)}/{len(cases)})", flush=True)
        return frozen_queries


@contextmanager
def capture_preprocessing() -> Iterator[list[dict[str, torch.Tensor]]]:
    captured: list[dict[str, torch.Tensor]] = []
    original_preprocess = reranker.model.preprocess

    def record_preprocess(
        inputs: Any,
        *arguments: Any,
        **keyword_arguments: Any,
    ) -> dict[str, torch.Tensor]:
        features = original_preprocess(inputs, *arguments, **keyword_arguments)
        captured.append({name: tensor for name, tensor in features.items() if isinstance(tensor, torch.Tensor)})
        return features

    reranker.model.preprocess = record_preprocess
    try:
        yield captured
    finally:
        del reranker.model.preprocess


def input_signature(features: list[dict[str, torch.Tensor]]) -> dict[str, Any]:
    batch_sizes: list[int] = []
    padded_lengths: list[int] = []
    actual_lengths: list[int] = []
    pair_hashes: list[str] = []
    for batch in features:
        identifiers = batch["input_ids"].detach().cpu()
        mask = batch["attention_mask"].detach().cpu()
        batch_sizes.append(int(identifiers.shape[0]))
        padded_lengths.append(int(identifiers.shape[1]))
        for token_ids, attention in zip(identifiers, mask, strict=True):
            actual = token_ids[attention.bool()].contiguous().numpy()
            actual_lengths.append(len(actual))
            pair_hashes.append(hashlib.sha256(actual.tobytes()).hexdigest())
    return {
        "batch_sizes": batch_sizes,
        "padded_lengths": padded_lengths,
        "actual_lengths": actual_lengths,
        "pair_token_hashes": pair_hashes,
        "padding_ratio": sum(size * length for size, length in zip(batch_sizes, padded_lengths, strict=True)) / sum(actual_lengths) - 1,
    }


class FixedInputRunner:
    def execute(
        self,
        frozen: dict[str, Any],
        setting: BatchSetting,
        phase: ExperimentPhase,
        repetition: int,
    ) -> dict[str, Any]:
        strategy = reranker.strategy_registry.resolve(setting.strategy)
        judgments = {int(identifier): grade for identifier, grade in frozen["judgments"].items()}
        with tracer().start_as_current_span("travelmate.reranking.batch_experiment") as span:
            span.set_attribute("evaluation.case_id", frozen["case_id"])
            span.set_attribute("evaluation.configuration", setting.name)
            span.set_attribute("evaluation.phase", phase.value)
            span.set_attribute("evaluation.query", frozen["query"])
            span.set_attribute("evaluation.candidate_fingerprint", frozen["candidate_fingerprint"])
            span.set_attribute("reranking.device", reranker.device)
            span.set_attribute("reranking.parameter_dtype", reranker._parameter_dtype())
            span.set_attribute("reranking.batch_size", setting.batch_size)
            span.set_attribute("reranking.candidate_count", len(frozen["texts"]))
            with capture_preprocessing() as captured:
                torch.cuda.synchronize()
                started_at = time.perf_counter()
                scores = strategy.execute(
                    reranker.model,
                    frozen["query"],
                    frozen["texts"],
                    setting.batch_size,
                    span,
                )
                torch.cuda.synchronize()
                elapsed_ms = (time.perf_counter() - started_at) * 1000
            if len(scores) != len(frozen["candidate_ids"]) or not all(math.isfinite(score) for score in scores):
                raise RuntimeError(f"Invalid reranking scores for {frozen['case_id']}")
            ordered = sorted(zip(frozen["candidate_ids"], scores, strict=True), key=lambda pair: pair[1], reverse=True)
            ranked_ids = [identifier for identifier, _ in ordered]
            metrics = ranking_metrics(ranked_ids, judgments)
            for name, value in metrics.items():
                span.set_attribute("evaluation." + name, value)
            span.set_attribute("reranking.elapsed_ms", elapsed_ms)
            signature = input_signature(captured)
            span.set_attribute("reranking.actual_batch_sizes", signature["batch_sizes"])
            span.set_attribute("reranking.padded_lengths", signature["padded_lengths"])
            return {
                "case_id": frozen["case_id"],
                "configuration": setting.name,
                "phase": phase.value,
                "repetition": repetition,
                "elapsed_ms": elapsed_ms,
                "candidate_fingerprint": frozen["candidate_fingerprint"],
                "scores_in_candidate_order": scores,
                "ranked_place_ids": ranked_ids,
                "metrics": metrics,
                "input_signature": signature,
                "trace_id": format(span.get_span_context().trace_id, "032x"),
            }


def summarize_settings(rows: list[dict[str, Any]]) -> dict[str, Any]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["configuration"]].append(row)
    baseline_rows = {row["case_id"]: row for row in grouped[BASELINE.name]}
    summaries: dict[str, Any] = {}
    for setting in SETTINGS:
        setting_rows = grouped[setting.name]
        means = {name: statistics.fmean(row["metrics"][name] for row in setting_rows) for name in setting_rows[0]["metrics"]}
        degradations = {
            name: sum(row["metrics"][name] + 1e-12 < baseline_rows[row["case_id"]]["metrics"][name] for row in setting_rows)
            for name in means
        }
        token_mismatches = [
            row["case_id"] for row in setting_rows
            if row["input_signature"]["pair_token_hashes"] != baseline_rows[row["case_id"]]["input_signature"]["pair_token_hashes"]
        ]
        summaries[setting.name] = {
            "strategy": setting.strategy.value,
            "batch_size": setting.batch_size,
            "case_count": len(setting_rows),
            "quality_means": means,
            "latency": latency_statistics([row["elapsed_ms"] for row in setting_rows]),
            "metric_regressions_by_case": degradations,
            "token_mismatch_cases": token_mismatches,
            "quality_gate_passed": not token_mismatches and not any(degradations.values()),
            "exact_rank_match_count": sum(row["ranked_place_ids"] == baseline_rows[row["case_id"]]["ranked_place_ids"] for row in setting_rows),
            "max_score_delta": max(
                abs(score - reference)
                for row in setting_rows
                for score, reference in zip(row["scores_in_candidate_order"], baseline_rows[row["case_id"]]["scores_in_candidate_order"], strict=True)
            ),
        }
    return summaries


async def experiment(args: argparse.Namespace) -> None:
    if reranker.device != "cuda" or embedder.device != "cuda":
        raise RuntimeError("This comparison requires both models on CUDA")
    if min(args.warmups, args.confirmation_cases, args.confirmation_repeats) < 1:
        raise ValueError("Warmup and confirmation settings must be positive")
    if args.output_dir.resolve().is_relative_to(args.dataset.resolve()):
        raise ValueError("Experiment outputs must stay outside the frozen dataset")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    provider = configure_tracing()
    all_cases = [
        case for case in read_jsonl(args.dataset / "generated/golden.jsonl")
        if "search" in case["evaluation_tracks"] and case["evaluation_group"] == "plannerLLM"
    ]
    cases = [case for case in all_cases if not any(case["input"]["conditions"].get(name) for name in ("area", "exclude_place_ids", "conversation"))]
    frozen = await FixedCandidateCollector().collect(cases, args.output_dir)
    runner = FixedInputRunner()
    for setting in SETTINGS:
        for _ in range(args.warmups):
            with tracer().start_as_current_span("reranking.batch_experiment.warmup") as span:
                reranker.strategy_registry.resolve(setting.strategy).execute(
                    reranker.model,
                    frozen[0]["query"],
                    frozen[0]["texts"],
                    setting.batch_size,
                    span,
                )
                torch.cuda.synchronize()
    rows: list[dict[str, Any]] = []
    for index, query in enumerate(frozen):
        offset = index % len(SETTINGS)
        rotated = SETTINGS[offset:] + SETTINGS[:offset]
        for setting in rotated:
            rows.append(runner.execute(query, setting, ExperimentPhase.SCREENING, 0))
            write_jsonl(args.output_dir / "screening_results.jsonl", rows)
            print(f"screen: {query['case_id']} {setting.name} ({len(rows)}/{len(frozen) * len(SETTINGS)}) {rows[-1]['elapsed_ms']:.0f}ms", flush=True)
    summaries = summarize_settings(rows)
    eligible = [setting for setting in SETTINGS if summaries[setting.name]["quality_gate_passed"]]
    selected = min(eligible, key=lambda setting: (summaries[setting.name]["latency"]["p95_ms"], summaries[setting.name]["latency"]["p50_ms"]))
    reference = BatchSetting(RerankingStrategyType.CROSS_ENCODER_PREDICT, selected.batch_size)
    if reference == selected:
        reference = BASELINE
    baseline = {row["case_id"]: row for row in rows if row["configuration"] == BASELINE.name}
    ordered_cases = sorted(frozen, key=lambda query: max(baseline[query["case_id"]]["input_signature"]["actual_lengths"]))
    indices = sorted(set(int(index) for index in np.linspace(0, len(ordered_cases) - 1, min(args.confirmation_cases, len(ordered_cases)))))
    confirmation_rows: list[dict[str, Any]] = []
    for repetition in range(args.confirmation_repeats):
        for index in indices:
            query = ordered_cases[index]
            pair = (reference, selected) if (repetition + index) % 2 else (selected, reference)
            for setting in dict.fromkeys(pair):
                confirmation_rows.append(runner.execute(query, setting, ExperimentPhase.CONFIRMATION, repetition))
                write_jsonl(args.output_dir / "confirmation_results.jsonl", confirmation_rows)
                print(f"confirm: {query['case_id']} {setting.name} repeat={repetition + 1} {confirmation_rows[-1]['elapsed_ms']:.0f}ms", flush=True)
    confirmation_gate = all(
        all(value + 1e-12 >= baseline[row["case_id"]]["metrics"][name] for name, value in row["metrics"].items())
        and row["input_signature"]["pair_token_hashes"] == baseline[row["case_id"]]["input_signature"]["pair_token_hashes"]
        for row in confirmation_rows if row["configuration"] == selected.name
    )
    confirmation_latency = {
        setting.name: latency_statistics([row["elapsed_ms"] for row in confirmation_rows if row["configuration"] == setting.name])
        for setting in dict.fromkeys((reference, selected))
    }
    report = {
        "status": "completed",
        "dataset_manifest_sha256": digest(args.dataset / "manifest.json"),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "case_count": len(cases),
        "excluded_case_count": len(all_cases) - len(cases),
        "excluded_case_ids": [case["case_id"] for case in all_cases if case not in cases],
        "model": reranker.model_name,
        "parameter_dtype": reranker._parameter_dtype(),
        "gpu_name": torch.cuda.get_device_name(),
        "baseline": BASELINE.name,
        "settings": summaries,
        "selected_setting": {"strategy": selected.strategy.value, "batch_size": selected.batch_size, "name": selected.name},
        "confirmation": {
            "case_ids": [ordered_cases[index]["case_id"] for index in indices],
            "repeats": args.confirmation_repeats,
            "latency": confirmation_latency,
            "quality_gate_passed": confirmation_gate,
        },
        "deployment_gate_passed": confirmation_gate and summaries[selected.name]["quality_gate_passed"],
        "notes": [
            "All six configurations use identical frozen candidate IDs and complete bodies per query; no token cap or candidate reduction is introduced.",
            "Quality gate requires identical unpadded token IDs and no per-query decrease in any ranking metric against FP32 batch 32.",
            "Screening latency is one measured run per query/configuration after global warmup; confirmation repeats a length-stratified query subset.",
            "Preprocessing records tensor references during timing; token hashing and quality scoring occur after timing.",
            "These times measure reranking only, excluding embedding, DB, Kafka and HTTP. Labels remain partial human judgments.",
            "FP16 is CUDA autocast; model parameters remain FP32. Batch warmup does not prove every input shape has been warmed.",
        ],
    }
    write_json(args.output_dir / "summary.json", report)
    if provider is not None:
        provider.force_flush(timeout_millis=30000)
        provider.shutdown()
    print(f"Batch experiment complete: {args.output_dir}; selected={selected.name}; quality_gate={report['deployment_gate_passed']}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=Path("/evaluation/datasets/v1.4.0"))
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=2)
    parser.add_argument("--confirmation-cases", type=int, default=12)
    parser.add_argument("--confirmation-repeats", type=int, default=3)
    args = parser.parse_args()
    asyncio.run(experiment(args))


if __name__ == "__main__":
    main()
