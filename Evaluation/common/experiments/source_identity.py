"""Match Gradle's runtime-source digest without copying a checkout or trusting a label."""
from hashlib import sha256
from pathlib import Path


def source_identity(root: Path) -> str:
    fingerprint = sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        name = "src/main/" + path.relative_to(root).as_posix()
        fingerprint.update(name.encode("utf-8") + b"\0" + path.read_bytes() + b"\0")
    return fingerprint.hexdigest()


def search_source_identity(root: Path) -> str:
    fingerprint = sha256()
    paths = [path for directory in ("app", "routers", "sql") for path in (root / directory).rglob("*")
             if path.is_file() and path.suffix in {".py", ".sql"}]
    for path in sorted(paths):
        fingerprint.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return fingerprint.hexdigest()


def evaluator_source_identity(root: Path) -> str:
    fingerprint = sha256()
    paths = [path for directory in ("common", "tracks") for path in (root / directory).rglob("*.py")]
    for path in sorted(paths):
        fingerprint.update(path.relative_to(root).as_posix().encode() + b"\0" + path.read_bytes() + b"\0")
    return fingerprint.hexdigest()
