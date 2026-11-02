"""게시 파일·정책 코드의 실행 바이트와 Git 텍스트 해시를 구분한다."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

RUN = Path(__file__).resolve().parent
ROOT = RUN.parents[4]
CODE = (
    "embedding-server/app/kafka_runtime.py",
    "embedding-server/app/contextual/connection_statements.py",
    "embedding-server/app/contextual/evidence_quality.py",
    "embedding-server/tests/test_contextual_evidence_quality.py",
    "embedding-server/tests/test_contextual_evidence_quality_runtime.py",
    "embedding-server/tests/test_contextual_evidence_quality_postgres.py",
    "Evaluation/tracks/contextual/evidence_quality_replay.py",
)


def digests(path: Path) -> dict[str, str]:
    content = path.read_bytes()
    return {"raw_sha256": hashlib.sha256(content).hexdigest(),
            "lf_sha256": hashlib.sha256(content.replace(b"\r\n", b"\n")).hexdigest()}


def main() -> None:
    replay = json.loads((RUN / "replay.json").read_text(encoding="utf-8"))
    assert len(replay["results"]) == 18
    assert all(result["relative_order_preserved"] and result["scores_preserved"] for result in replay["results"])
    focal = [result for result in replay["results"] if result["id"] == "unnamed-connection"]
    assert all(result["original_top_20_unchanged"] and result["held_count"] == 1 for result in focal)
    tests = json.loads((RUN / "tests.json").read_text(encoding="utf-8"))
    assert tests["successful"] and tests["passed"] == 173 and tests["tests_run"] == 174
    document = {
        "base_commit": "c5d0c7bdbaf3d216d06a862b295bbfdfc8e4d490",
        "code": {path: digests(ROOT / path) for path in CODE},
        "files": {path.name: digests(path) for path in sorted(RUN.iterdir())
                  if path.is_file() and path.name != "publication.json"},
        "input_sha256": replay["input_sha256"],
        "hash_basis": "raw_sha256 is the local execution bytes; lf_sha256 normalizes CRLF to LF for Git publication.",
    }
    (RUN / "publication.json").write_text(json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"artifacts": len(document["files"]), "code_files": len(CODE), "saved_cases": 18}))


if __name__ == "__main__":
    main()
