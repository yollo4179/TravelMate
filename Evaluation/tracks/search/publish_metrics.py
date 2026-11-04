"""Publish measured search means as visible LangSmith outputs and feedback."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
import os
import math
import time
from pathlib import Path
import sys
from typing import Any
import uuid

from dotenv import load_dotenv
from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.io import read_json, read_jsonl, write_json
from common.paths import EVALUATION_ROOT


def publish(collection_dir: Path, embedding_run: Path, reranking_run: Path) -> dict[str, Any]:
    load_dotenv(EVALUATION_ROOT.parent / ".env", override=False)
    load_dotenv(EVALUATION_ROOT.parent / "Docker/build/stack/runtime.env", override=False)
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        raise RuntimeError("LangSmith API key is missing")
    project = os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability")
    client = Client(
        api_key=api_key,
        api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        auto_batch_tracing=False,
    )
    summaries = {"embedding": read_json(embedding_run / "summary.json"), "reranking": read_json(reranking_run / "summary.json")}
    scored_ids = {
        mode: {row["case_id"] for row in read_jsonl(run / "scores/results.jsonl")}
        for mode, run in (("embedding", embedding_run), ("reranking", reranking_run))
    }
    if scored_ids["embedding"] != scored_ids["reranking"]:
        raise ValueError("Mean comparison requires the same scored cases")
    collection = read_json(collection_dir / "collection_summary.json")
    outputs = {
        "scored_case_count": len(scored_ids["embedding"]),
        "requested_case_count": collection["selected_case_count"],
        "excluded_cases": summaries["reranking"]["invalid_or_missing"],
        "quality_means": {
            mode: {name: metric["mean"] for name, metric in summary["code_metrics_and_gpt_scores"].items()}
            for mode, summary in summaries.items()
        },
        "by_known_relevant_count": {mode: summary["by_recommendation_scope"] for mode, summary in summaries.items()},
        "request_latency_80_cases": collection["by_mode"],
        "measurement_notes": [
            "Quality means use 60 fully applied cases; 20 partial-condition cases are excluded.",
            "Relevance judgments are partial. Unjudged results are not confirmed errors.",
            f"Reranker configuration: {collection.get('reranking_configuration', 'legacy CUDA diagnostic mode, batch 32')}. No LLM call was made.",
            "This summary publishes previously measured results; its own run duration is upload time.",
        ],
    }
    run_id = uuid.uuid5(uuid.NAMESPACE_URL, "travelmate.search.metrics.summary:" + collection_dir.name)
    now = datetime.now(timezone.utc)
    publish_path = collection_dir / "langsmith_metrics_publish.json"
    try:
        client.read_run(run_id)
        exists = True
    except LangSmithNotFoundError:
        exists = False
    if exists:
        client.update_run(run_id, outputs=outputs)
    else:
        client.create_run(
            "travelmate.search.metrics.summary",
            inputs={"collection_run_id": collection_dir.name, "dataset_version": "1.4.0", "quality_denominator": len(scored_ids["embedding"])},
            run_type="chain",
            project_name=project,
            id=run_id,
            start_time=now,
            end_time=now,
            outputs=outputs,
            tags=["search-quality-means", "measured-results", "60-scored-20-excluded"],
        )
    for attempt in range(6):
        try:
            summary_run = client.read_run(run_id)
            break
        except LangSmithNotFoundError:
            if attempt == 5:
                raise
            time.sleep(min(0.5 * (attempt + 1), 2.0))
    existing_feedback = {item.key: item.score for item in client.list_feedback(run_ids=[run_id])}
    expected_feedback: dict[str, float] = {}
    for mode, means in outputs["quality_means"].items():
        for metric, score in means.items():
            if not metric.startswith(("top_", "recall_", "precision_", "ndcg_", "mrr_", "map_", "f1_")):
                continue
            key = f"{mode}.{metric}"
            expected_feedback[key] = score
            if key in existing_feedback:
                continue
            client.create_feedback(
                run_id,
                key,
                score=score,
                feedback_id=uuid.uuid5(run_id, key),
                session_id=summary_run.session_id,
                comment="Macro mean over the same 60 fully applied, human-labeled search cases; partial judgments.",
            )
    uploaded = {item.key: item.score for item in client.list_feedback(run_ids=[run_id])}
    # LangSmith feedback returns these numeric scores rounded to four decimals.
    if any(uploaded.get(key) is None or not math.isclose(uploaded[key], score, abs_tol=0.000051) for key, score in expected_feedback.items()):
        raise RuntimeError("Published mean feedback did not match local measured scores")
    started = datetime.strptime(collection_dir.name[:16], "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
    complete_runs = [
        run for run in client.list_runs(project_name=project, is_root=True, start_time=started - timedelta(minutes=1))
        if run.name == "travelmate.search.evaluation_case"
        and (run.extra or {}).get("metadata", {}).get("otel.span.evaluation.case_id") in scored_ids["reranking"]
    ]
    sample = next((run for run in complete_runs if run.extra["metadata"]["otel.span.evaluation.case_id"] == "PLR-TM-palaces-01"), None)
    summary_run = client.read_run(run_id)
    report = {
        "summary_url": client.get_run_url(run=summary_run, project_name=project),
        "summary_run_id": str(run_id),
        "verified_feedback_count": len(expected_feedback),
        "feedback_absolute_tolerance": 0.000051,
        "scored_case_count": len(scored_ids["reranking"]),
        "complete_case_trace_count": len(complete_runs),
        "scored_sample_url": client.get_run_url(run=sample, project_name=project) if sample else None,
        "scored_sample_case_id": "PLR-TM-palaces-01" if sample else None,
    }
    write_json(publish_path, report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--collection-dir", type=Path, required=True)
    parser.add_argument("--embedding-run", type=Path, required=True)
    parser.add_argument("--reranking-run", type=Path, required=True)
    args = parser.parse_args()
    print(publish(args.collection_dir, args.embedding_run, args.reranking_run))


if __name__ == "__main__":
    main()
