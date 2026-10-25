"""Deterministic data I/O and separation of model inputs from evaluation gold."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from .contracts import TOOL_ARGUMENT_SCHEMAS, TOOL_CONTRACTS
from common.paths import DEFAULT_DATASET


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8-sig").splitlines() if line.strip()]


def write_json(path: Path, document: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8", newline="\n")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_digest(document: Any) -> str:
    encoded = json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def materialize_input(
    case: dict[str, Any],
    corpus: dict[int, dict[str, Any]],
    *,
    persona_profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    supplied = case["input"]
    persona = persona_profile if persona_profile is not None else read_json(DEFAULT_DATASET / "source/persona/guide_v1.json")
    return {
        **supplied,
        "persona": {**persona, **supplied.get("persona", {})},
        "tools": [{
            "type": "function",
            "function": {
                "name": name, "description": TOOL_CONTRACTS["tools"][name]["effect"],
                "parameters": schema,
            },
        } for name, schema in TOOL_ARGUMENT_SCHEMAS.items()],
        "candidates": [corpus[place_id] for place_id in supplied.get("candidate_place_ids", [])],
    }


def export_inputs(
    cases: list[dict[str, Any]],
    corpus: dict[int, dict[str, Any]],
    *,
    persona_profile: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    rows = []
    for case in cases:
        prepared = {
            "model_input": materialize_input(case, corpus, persona_profile=persona_profile),
            "harness_fixtures": case.get("fixtures", {}),
        }
        rows.append({
            "case_id": case["case_id"],
            **prepared,
            "input_sha256": canonical_digest(prepared),
        })
    return rows
