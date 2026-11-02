"""Archive an existing batch report without running or importing the C08 experiment."""
from __future__ import annotations

import argparse
import asyncio
from pathlib import Path
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from common.dataset.io import digest, read_json, read_jsonl, write_json
from common.execution.control import load_control
from common.observability.langsmith_transport import langsmith_transport, publish_artifact


def build_legacy_artifact(experiment_dir: Path, configurations: list[str]) -> dict[str, Any]:
    report = read_json(experiment_dir / "summary.json")
    queries = read_jsonl(experiment_dir / "frozen_candidates.jsonl")
    measured = read_jsonl(experiment_dir / "screening_results.jsonl")
    case_ids = {row["case_id"] for row in queries}
    if len(case_ids) != len(queries) or not case_ids or len(configurations) != len(set(configurations)) or not configurations:
        raise ValueError("The preserved experiment needs unique cases and explicitly selected configurations")
    if not set(configurations) <= report["settings"].keys():
        raise ValueError("No missing batch configuration is generated")
    for configuration in configurations:
        selected = [row for row in measured if row["configuration"] == configuration]
        if len(selected) != len(case_ids) or {row["case_id"] for row in selected} != case_ids:
            raise ValueError("The preserved measurement rows do not cover the selected report")
    return {
        "case_ids": sorted(case_ids), "quality_status": "legacy_report_only", "metrics": {},
        "reported_settings": {name: report["settings"][name] for name in configurations},
        "reported_gpu": report.get("gpu_name"), "reported_model": report.get("model"),
        "reported_baseline": report.get("baseline"),
        "source_sha256": {name: digest(experiment_dir / name) for name in ("summary.json", "frozen_candidates.jsonl", "screening_results.jsonl")},
        "limitations": ["These are historical report values, not newly verified current-search quality or latency.", "The C08 experiment, embeddings, search and reranker are not imported or rerun.", "No source run is relabeled LIVE and no verified-quality feedback is created."],
    }


async def publish(arguments: argparse.Namespace) -> None:
    control = load_control(arguments.config, arguments.output_dir, arguments.mock_responses)
    try:
        artifact = build_legacy_artifact(arguments.experiment_dir, control.settings.parameter("batch_configurations"))
        if artifact["source_sha256"] != control.settings.parameter("source_sha256"):
            raise ValueError("Historical source files differ from the explicit execution configuration")
        write_json(arguments.output_dir / "artifact.json", artifact)
        async with langsmith_transport(control, arguments.api_key_env) as transport:
            receipt = await publish_artifact(control, transport, name="travelmate.reranking.historical_report", artifact=artifact)
        write_json(arguments.output_dir / "publication.json", receipt)
    except Exception as exception:
        control.reject_result(type(exception).__name__)
        write_json(arguments.output_dir / "failure.json", {**control.summary(), "status": "failed", "error_type": type(exception).__name__})
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--mock-responses", type=Path)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--api-key-env", default="LANGSMITH_API_KEY")
    asyncio.run(publish(parser.parse_args()))


if __name__ == "__main__":
    main()
