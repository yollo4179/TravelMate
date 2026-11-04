"""Publish measured batch comparison tables and numeric LangSmith feedback."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import math
import os
from pathlib import Path
import sys
import time
from typing import Any
import uuid

from dotenv import load_dotenv
from langsmith import Client
from langsmith.utils import LangSmithNotFoundError

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from common.dataset.io import read_json, read_jsonl, write_json
from common.paths import EVALUATION_ROOT


def ensure_run(
    client: Client,
    *,
    identifier: uuid.UUID,
    name: str,
    project: str,
    inputs: dict[str, Any],
    outputs: dict[str, Any],
    experiment_name: str,
) -> Any:
    try:
        client.read_run(identifier)
    except LangSmithNotFoundError:
        now = datetime.now(timezone.utc)
        client.create_run(
            name,
            inputs=inputs,
            outputs=outputs,
            run_type="chain",
            project_name=project,
            id=identifier,
            start_time=now,
            end_time=now,
            tags=["reranking-batch-comparison", experiment_name],
        )
    else:
        client.update_run(identifier, outputs=outputs)
    for attempt in range(6):
        try:
            return client.read_run(identifier)
        except LangSmithNotFoundError:
            if attempt == 5:
                raise
            time.sleep(min(0.5 * (attempt + 1), 2.0))
    raise RuntimeError("LangSmith run did not become visible")


def publish(output_dir: Path) -> dict[str, Any]:
    load_dotenv(EVALUATION_ROOT.parent / ".env", override=False)
    load_dotenv(EVALUATION_ROOT.parent / "Docker/build/stack/runtime.env", override=False)
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        raise RuntimeError("LangSmith key is missing")
    project = os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability")
    client = Client(
        api_key=api_key,
        api_url=os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com"),
        auto_batch_tracing=False,
    )
    report = read_json(output_dir / "summary.json")
    frozen_queries = {query["case_id"]: query for query in read_jsonl(output_dir / "frozen_candidates.jsonl")}
    measured_rows = read_jsonl(output_dir / "screening_results.jsonl")
    overview_id = uuid.uuid5(uuid.NAMESPACE_URL, "travelmate.batch.overview:" + output_dir.name)
    overview = ensure_run(
        client,
        identifier=overview_id,
        name="travelmate.reranking.batch_comparison.summary",
        project=project,
        inputs={"experiment_id": output_dir.name, "case_count": report["case_count"]},
        outputs=report,
        experiment_name=output_dir.name,
    )
    links: dict[str, str] = {}
    feedback_count = 0
    for configuration, measurements in report["settings"].items():
        identifier = uuid.uuid5(overview_id, configuration)
        case_results = []
        for row in (row for row in measured_rows if row["configuration"] == configuration):
            frozen = frozen_queries[row["case_id"]]
            names = dict(zip(frozen["candidate_ids"], frozen["candidate_names"], strict=True))
            scores = dict(zip(frozen["candidate_ids"], row["scores_in_candidate_order"], strict=True))
            case_results.append({
                "case_id": row["case_id"],
                "query": frozen["query"],
                "candidate_fingerprint": row["candidate_fingerprint"],
                "elapsed_ms": row["elapsed_ms"],
                "metrics": row["metrics"],
                "known_relevant_ids": [int(identifier) for identifier, grade in frozen["judgments"].items() if grade >= 2],
                "top_results": [{"place_id": identifier, "name": names[identifier], "score": scores[identifier]} for identifier in row["ranked_place_ids"][:10]],
                "actual_batch_sizes": row["input_signature"]["batch_sizes"],
                "padded_lengths": row["input_signature"]["padded_lengths"],
            })
        run = ensure_run(
            client,
            identifier=identifier,
            name="travelmate.reranking." + configuration,
            project=project,
            inputs={"experiment_id": output_dir.name, "baseline": report["baseline"]},
            outputs={**measurements, "case_results": case_results},
            experiment_name=output_dir.name,
        )
        existing = {item.key: item.score for item in client.list_feedback(run_ids=[identifier])}
        for metric, score in measurements["quality_means"].items():
            if metric in existing:
                continue
            client.create_feedback(
                identifier,
                metric,
                score=score,
                feedback_id=uuid.uuid5(identifier, metric),
                session_id=run.session_id,
                comment=f"Macro mean over {report['case_count']} frozen-input judged queries; no token cap or candidate reduction.",
            )
        verified = {item.key: item.score for item in client.list_feedback(run_ids=[identifier])}
        if any(verified.get(metric) is None or not math.isclose(verified[metric], score, abs_tol=0.000051) for metric, score in measurements["quality_means"].items()):
            raise RuntimeError(f"Feedback verification failed for {configuration}")
        feedback_count += len(measurements["quality_means"])
        links[configuration] = client.get_run_url(run=run, project_name=project)
    publication = {
        "overview_url": client.get_run_url(run=overview, project_name=project),
        "configuration_urls": links,
        "verified_feedback_count": feedback_count,
    }
    write_json(output_dir / "langsmith_publication.json", publication)
    return publication


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    print(publish(args.output_dir))


if __name__ == "__main__":
    main()
