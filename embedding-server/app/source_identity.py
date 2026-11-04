"""Runtime code identity excludes model weights, secrets, results and caches."""
from functools import lru_cache
from hashlib import sha256
from pathlib import Path


@lru_cache(maxsize=1)
def source_identity() -> str:
    root = Path(__file__).resolve().parents[1]
    paths = [path for directory in ("app", "routers", "sql") for path in (root / directory).rglob("*")
             if path.is_file() and path.suffix in {".py", ".sql"}]
    result = sha256()
    for path in sorted(paths):
        result.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return result.hexdigest()


RUNTIME_SOURCE_SHA256 = source_identity()
