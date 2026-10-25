"""Stable code, dataset and result locations, independent of the working directory."""
from pathlib import Path

EVALUATION_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATASET = EVALUATION_ROOT / "datasets/v1.4.0"
RUNS_ROOT = EVALUATION_ROOT / "runs"
RUBRIC_BY_GROUP = {"plannerLLM": "plan_quality.md", "managerLLM": "behavior.md"}


def rubric_path(dataset: Path, group: str) -> Path:
    return dataset / "rubrics" / RUBRIC_BY_GROUP[group]
