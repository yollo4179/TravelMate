"""Allocate immutable run directories and record evaluator/source provenance."""
from datetime import datetime, timezone
from pathlib import Path
import subprocess
from typing import Any
import uuid

from common.dataset.io import digest, write_json
from common.paths import EVALUATION_ROOT, RUNS_ROOT
from .tracks import Track


def allocate_run(track: Track, dataset: Path, output: Path | None = None) -> tuple[str, Path]:
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    target = output if output is not None else RUNS_ROOT / track.value / dataset.name / run_id
    if target.resolve().is_relative_to(dataset.resolve()) or target.resolve().is_relative_to((EVALUATION_ROOT / "datasets").resolve()):
        raise ValueError("Run results must be outside the dataset directory")
    target.mkdir(parents=True, exist_ok=False)
    return run_id, target


def evaluator_git_sha() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=EVALUATION_ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def write_run_record(*, run_id: str, track: Track, dataset: Path, output: Path, scope: dict[str, Any], status: str) -> None:
    write_json(output / "run.json", {
        "run_id": run_id, "track": track.value, "dataset_version": dataset.name,
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "evaluator_git_sha": evaluator_git_sha(),
        "dataset_manifest_sha256": digest(dataset / "manifest.json"),
        "persona_sha256": digest(dataset / "source/persona/guide_v1.json"),
        "scope": scope, "status": status,
        "execution": "score_recorded_responses; no application API calls",
        "latency_measurement": "not_collected_by_this_runner",
    })


def update_latest(track: Track, dataset: Path, run_id: str, output: Path) -> None:
    parent = RUNS_ROOT / track.value / dataset.name
    parent.mkdir(parents=True, exist_ok=True)
    temporary = parent / (".latest-" + run_id + ".json")
    write_json(temporary, {"run_id": run_id, "path": str(output.resolve())})
    temporary.replace(parent / "latest.json")
