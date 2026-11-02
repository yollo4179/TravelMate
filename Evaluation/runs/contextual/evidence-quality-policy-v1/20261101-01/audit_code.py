"""기존 검색·활성 상한 구현의 보존 여부를 기준 커밋과 비교한다."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[5]
BASE = "c5d0c7bdbaf3d216d06a862b295bbfdfc8e4d490"
RUNTIME = "embedding-server/app/kafka_runtime.py"
UNCHANGED_FILES = (
    "embedding-server/app/contextual/pipeline.py",
    "embedding-server/app/contextual/contracts.py",
    "embedding-server/app/contextual/retrieval.py",
    "embedding-server/app/contextual/ranking.py",
    "embedding-server/app/contextual/relation_vectors.py",
    "embedding-server/app/contextual/schema.sql",
)


def baseline(path: str) -> str:
    return subprocess.check_output(["git", "show", f"{BASE}:{path}"], cwd=ROOT).decode("utf-8")


def method(tree: ast.Module, name: str) -> str:
    runtime = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "KafkaRuntime")
    selected = next(node for node in runtime.body if isinstance(node, ast.AsyncFunctionDef) and node.name == name)
    return ast.dump(selected, include_attributes=False)


def main() -> None:
    current = ast.parse((ROOT / RUNTIME).read_text(encoding="utf-8"))
    original = ast.parse(baseline(RUNTIME))
    methods = {
        name: method(current, name) == method(original, name)
        for name in ("_retrieve_candidates", "_retrieve_evidence", "_index_place_job")
    }
    unchanged = {
        path: (ROOT / path).read_text(encoding="utf-8") == baseline(path)
        for path in UNCHANGED_FILES
    }
    constants = [node for node in current.body if isinstance(node, ast.Assign)
                 and any(isinstance(target, ast.Name) and target.id == "RETRIEVE_TOP_K" for target in node.targets)]
    candidate_limit = ast.literal_eval(constants[0].value)
    assert all(methods.values()) and all(unchanged.values()) and candidate_limit == 30
    report = {"base_commit": BASE, "unchanged_method_ast": methods, "unchanged_files": unchanged,
              "candidate_limit": candidate_limit, "distance_filter_unchanged": methods["_retrieve_candidates"],
              "runtime_lf_sha256": hashlib.sha256((ROOT / RUNTIME).read_bytes().replace(b"\r\n", b"\n")).hexdigest()}
    Path(__file__).with_name("invariants.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
