"""Atomic report writes and credential-safe failures shared by both evaluators."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any


def atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp")
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(content)
        temporary_path.replace(path)
    finally:
        temporary_path.unlink(missing_ok=True)


def write_json(path: Path, payload: dict[str, Any]) -> None:
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    atomic_write(path, "".join(json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n" for row in rows))


def safe_failure(exception: Exception) -> dict[str, str]:
    guidance = {
        "AuthenticationError": "Check OPENAI_API_KEY and the OpenAI project permissions.",
        "PermissionDeniedError": "Check access to the configured OpenAI models.",
        "RateLimitError": "Check OpenAI API quota, billing and rate limits.",
        "APIConnectionError": "Check network access to the OpenAI API.",
        "APITimeoutError": "The OpenAI request timed out; no partial batch was published.",
        "ModuleNotFoundError": "Install this version's requirements-evaluation.txt in the evaluation environment.",
        "ImportError": "Install this version's requirements-evaluation.txt in the evaluation environment.",
    }
    return {
        "error_type": type(exception).__name__,
        "message": guidance.get(type(exception).__name__, "Evaluation failed. Check API access, dependencies and metric inputs. No partial scores were published."),
    }
