"""검증 자료와 코드의 로컬 바이트·Git 텍스트 해시를 보존한다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[4]
CODE = (
    "embedding-server/app/kafka_runtime.py",
    "embedding-server/tests/contextual_search_fixtures.py",
    "embedding-server/tests/test_contextual_general_search_contract.py",
    "Evaluation/tracks/contextual/general_search_scope_replay.py",
    "Evaluation/tracks/contextual/evidence_quality_replay.py",
    "Evaluation/tracks/contextual/experiments/connection_quality/connection_statements.py",
    "Evaluation/tracks/contextual/experiments/connection_quality/evidence_quality.py",
    "Evaluation/tracks/contextual/experiments/connection_quality/test_policy.py",
)


def digests(path: Path) -> dict[str, str]:
    content = path.read_bytes()
    return {"raw_sha256": hashlib.sha256(content).hexdigest(),
            "lf_sha256": hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()}


def main() -> None:
    replay = json.loads((RUN / "replay.json").read_text(encoding="utf-8"))
    tests = json.loads((RUN / "tests.json").read_text(encoding="utf-8"))
    assert tests["successful"] and tests["passed"] == 163 and tests["tests_run"] == 164
    assert len(replay["results"]) == 18
    assert all(case["same_full_order_scores_and_evidence_as_pre_policy"] for case in replay["results"])
    assert all(replay["unchanged_method_ast"].values()) and all(replay["preserved_files"].values())
    assert not replay["application_policy_imports"]
    publication = {
        "base_commit": "87e06d3e7685f252c2008c672343f58011b0123c",
        "code": {path: digests(ROOT / path) for path in CODE},
        "files": {path.name: digests(path) for path in sorted(RUN.iterdir())
                  if path.is_file() and path.name != "publication.json"},
        "input_sha256": replay["input_sha256"],
        "hash_basis": "raw_sha256 is the execution bytes; lf_sha256 normalizes CRLF to LF for Git publication.",
    }
    (RUN / "publication.json").write_text(json.dumps(publication, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifacts": len(publication["files"]), "code_files": len(CODE), "saved_cases": 18}))


if __name__ == "__main__":
    main()
