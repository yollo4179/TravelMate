"""Evaluate API results with ID metrics, reference-based metrics, or a reference-free MD judge."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ragas_support.backend import RagasBackend
from ragas_support.inputs import EvaluationBatch, load_batch
from ragas_support.precheck import build_precheck
from ragas_support.reporting import safe_failure, write_json, write_jsonl
from ragas_support.settings import (
    ID_METRICS, LLM_METRICS, EvaluatorSettings, MetricName, RunMode, RunStatus,
)

ROOT = Path(__file__).resolve().parent


class EvaluationBackend(Protocol):
    @property
    def version(self) -> str: ...

    async def score_ids(self, batch: EvaluationBatch) -> list[dict[str, Any]]: ...

    async def score_llm(
        self,
        batch: EvaluationBatch,
        settings: EvaluatorSettings,
    ) -> list[dict[str, Any]]: ...


def score_summary(
    rows: list[dict[str, Any]],
    metrics: tuple[MetricName, ...],
    batch: EvaluationBatch,
) -> dict[str, dict[str, float]]:
    expected = {
        (version, sample["case_id"])
        for version, samples in batch.samples_by_version.items()
        for sample in samples
    }
    actual = {(row["strategy_version"], row["case_id"]) for row in rows}
    if len(rows) != len(expected) or actual != expected:
        raise ValueError("Incomplete metric batch; partial scores were not published")
    return {
        version: {
            metric.value: sum(float(row[metric.value]) for row in rows if row["strategy_version"] == version)
            / len(samples)
            for metric in metrics
        }
        for version, samples in batch.samples_by_version.items()
    }


async def run_evaluation(
    *,
    root: Path,
    output: Path,
    settings: EvaluatorSettings,
    mode: RunMode,
    precheck_only: bool = False,
    backend: EvaluationBackend | None = None,
    rubric_path: Path | None = None,
    rubric_backend: Any = None,
) -> int:
    if mode == RunMode.JUDGE:
        from ragas_support.judge import run_markdown_judge
        return await run_markdown_judge(
            root=root, output=output, settings=settings,
            rubric_path=rubric_path or ROOT / "LLM_JUDGE_RUBRIC.md",
            precheck_only=precheck_only, backend=rubric_backend,
        )
    batch = load_batch(root)
    run_id = str(uuid.uuid4())
    provenance = {
        "run_id": run_id,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "dataset_version": "1.3.0",
        "paired_case_count": batch.paired_case_count,
        "input_sha256": batch.input_hashes,
        "review_statuses": batch.review_statuses,
        "skipped_case_counts": batch.skipped,
        "selection_scope": "same completed, condition-complete paired cases as the ID comparison",
    }
    precheck = {**provenance, **build_precheck(batch, settings)}
    write_json(output / "ragas_llm_precheck.json", precheck)
    if precheck_only:
        print(json.dumps(precheck, ensure_ascii=False, indent=2))
        return 0 if precheck["status"] == RunStatus.READY else 2
    if batch.paired_case_count == 0:
        print("완료되고 조건을 충족한 공통 평가 문항이 없습니다.")
        return 2
    evaluator = backend or RagasBackend()

    if mode in (RunMode.ALL, RunMode.ID):
        try:
            id_rows = await evaluator.score_ids(batch)
            averages = score_summary(id_rows, ID_METRICS, batch)
            id_summary = {
                **provenance,
                "status": RunStatus.COMPLETED.value,
                "ragas_version": evaluator.version,
                "metrics": [metric.value for metric in ID_METRICS],
                "metric_scope": "ID sets; retrieval ordering is not considered",
                "judgment_source": "review_notes_filled_v1.3.0.csv",
                "relevance_threshold": 2,
                "eligibility_source": "recomputed from execution_status, condition_coverage and positive CSV IDs",
                "judgment_coverage": "Unjudged IDs remain in the ID precision denominator; this is not fully judged recommendation accuracy.",
                "scores_by_strategy_version": averages,
                "results_file": "ragas_results.jsonl",
                "score_count": len(id_rows),
            }
            write_jsonl(output / "ragas_results.jsonl", [{**row, "run_id": run_id} for row in id_rows])
            write_json(output / "ragas_summary.json", id_summary)
            print(f"ID 평가 완료: 공통 {batch.paired_case_count}문항, {len(id_rows)}개 버전별 결과")
        except Exception as exception:
            write_json(output / "ragas_summary.json", {**provenance, "status": RunStatus.FAILED.value, "score_count": 0, "results_file": None, **safe_failure(exception)})
            print("ID 평가 실패: ragas_summary.json을 확인하세요.")
            return 1

    if mode == RunMode.ID:
        return 0
    llm_summary: dict[str, Any] = {
        **provenance,
        "status": precheck["status"],
        "metrics": [metric.value for metric in LLM_METRICS],
        "execution_policy": "all_or_none",
        "evaluator": settings.public_settings(),
        "score_count": 0,
        "results_file": None,
        "previous_result_file_preserved": (output / "ragas_llm_results.jsonl").exists(),
    }
    if precheck["status"] != RunStatus.READY:
        write_json(output / "ragas_llm_summary.json", llm_summary)
        print("LLM 평가 보류: ragas_llm_precheck.json의 지표별 reasons를 확인하세요.")
        return 2

    started = time.perf_counter()
    try:
        llm_rows = await evaluator.score_llm(batch, settings)
        averages = score_summary(llm_rows, LLM_METRICS, batch)
        # All cases, versions and metrics must finish before any LLM score file is replaced.
        published = [{**row, "run_id": run_id} for row in llm_rows]
        write_jsonl(output / "ragas_llm_results.jsonl", published)
        llm_summary.update({
            "status": RunStatus.COMPLETED.value,
            "ragas_version": evaluator.version,
            "scores_by_strategy_version": averages,
            "score_count": len(llm_rows),
            "metric_value_count": len(llm_rows) * len(LLM_METRICS),
            "results_file": "ragas_llm_results.jsonl",
            "evaluation_duration_seconds": time.perf_counter() - started,
        })
        precheck.update({"status": RunStatus.COMPLETED.value, "score_count": len(llm_rows), "llm_connection_verified": True})
        for entry in precheck["metrics"].values():
            entry["status"] = RunStatus.COMPLETED.value
        print(f"LLM 평가 완료: 공통 {batch.paired_case_count}문항, 세 지표 모두 완료")
    except Exception as exception:
        llm_summary.update({"status": RunStatus.FAILED.value, **safe_failure(exception)})
        precheck.update({"status": RunStatus.FAILED.value, **safe_failure(exception)})
        write_json(output / "ragas_llm_summary.json", llm_summary)
        write_json(output / "ragas_llm_precheck.json", precheck)
        print("LLM 평가 실패: 부분 점수는 저장하지 않았습니다. ragas_llm_summary.json을 확인하세요.")
        return 1
    write_json(output / "ragas_llm_summary.json", llm_summary)
    write_json(output / "ragas_llm_precheck.json", precheck)
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Directory containing the two API JSONL files and review CSV")
    parser.add_argument("--output-dir", type=Path, help="Defaults to --root; input API files are never rewritten")
    parser.add_argument("--config", type=Path, help="Defaults to ragas_config.json alongside this runner")
    parser.add_argument("--env-file", type=Path, help="Explicit optional .env file containing OPENAI_API_KEY")
    parser.add_argument("--mode", choices=[mode.value for mode in RunMode], default=RunMode.ALL.value)
    parser.add_argument("--rubric", type=Path, help="Markdown rubric for --mode judge; defaults to LLM_JUDGE_RUBRIC.md")
    parser.add_argument("--precheck-only", action="store_true", help="No Ragas imports or OpenAI requests; write prerequisite report only")
    arguments = parser.parse_args()
    if arguments.env_file:
        if not arguments.env_file.is_file():
            parser.error("--env-file does not exist")
        from dotenv import load_dotenv
        load_dotenv(arguments.env_file, override=False)
    settings = EvaluatorSettings.load(arguments.config or ROOT / "ragas_config.json", os.environ)
    try:
        code = asyncio.run(run_evaluation(
            root=arguments.root,
            output=arguments.output_dir or arguments.root,
            settings=settings,
            mode=RunMode(arguments.mode),
            precheck_only=arguments.precheck_only,
            rubric_path=arguments.rubric,
        ))
    except (FileNotFoundError, ValueError, KeyError) as exception:
        print(f"입력 검증 실패 ({type(exception).__name__}). API JSONL·CSV·golden·원문·MD와 경로를 확인하세요.")
        code = 1
    raise SystemExit(code)


if __name__ == "__main__":
    main()
