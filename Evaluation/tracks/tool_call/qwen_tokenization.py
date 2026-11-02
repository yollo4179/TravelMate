"""Compatibility import of the runtime vocabulary-only implementation."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from Server.token_budget.qwen_tokenization import (  # noqa: E402,F401
    GgufType, NativeQwenVocabulary, file_sha256, independent_byte_bpe, read_gguf_metadata,
)
