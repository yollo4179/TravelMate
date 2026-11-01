"""Pinned, vocabulary-only tokenization for offline verification, outside the runtime guard."""
from __future__ import annotations

import ctypes
from enum import IntEnum
import hashlib
import os
from pathlib import Path
import struct
from typing import Any, BinaryIO


class GgufType(IntEnum):
    UINT8 = 0
    INT8 = 1
    UINT16 = 2
    INT16 = 3
    UINT32 = 4
    INT32 = 5
    FLOAT32 = 6
    BOOL = 7
    STRING = 8
    ARRAY = 9
    UINT64 = 10
    INT64 = 11
    FLOAT64 = 12


SCALAR_FORMATS = {
    GgufType.UINT8: "B", GgufType.INT8: "b", GgufType.UINT16: "H", GgufType.INT16: "h",
    GgufType.UINT32: "I", GgufType.INT32: "i", GgufType.FLOAT32: "f", GgufType.BOOL: "?",
    GgufType.UINT64: "Q", GgufType.INT64: "q", GgufType.FLOAT64: "d",
}


def file_sha256(path: Path) -> str:
    checksum = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(4 * 1024 * 1024):
            checksum.update(chunk)
    return checksum.hexdigest()


def _scalar(source: BinaryIO, format_code: str) -> Any:
    length = struct.calcsize("<" + format_code)
    content = source.read(length)
    if len(content) != length:
        raise ValueError("Incomplete GGUF metadata")
    return struct.unpack("<" + format_code, content)[0]


def _string(source: BinaryIO) -> str:
    length = _scalar(source, "Q")
    if length > 16 * 1024 * 1024:
        raise ValueError("Unexpected GGUF metadata string size")
    content = source.read(length)
    if len(content) != length:
        raise ValueError("Incomplete GGUF string")
    return content.decode("utf-8")


def _value(source: BinaryIO, kind: GgufType) -> Any:
    if kind == GgufType.STRING:
        return _string(source)
    if kind == GgufType.ARRAY:
        element_kind = GgufType(_scalar(source, "I"))
        length = _scalar(source, "Q")
        if length > 2_000_000:
            raise ValueError("Unexpected GGUF metadata array size")
        return [_value(source, element_kind) for _ in range(length)]
    return _scalar(source, SCALAR_FORMATS[kind])


def read_gguf_metadata(path: Path) -> dict[str, Any]:
    with path.open("rb") as source:
        if source.read(4) != b"GGUF" or _scalar(source, "I") != 3:
            raise ValueError("This verification only supports GGUF v3")
        tensor_count = _scalar(source, "Q")
        metadata_count = _scalar(source, "Q")
        metadata = {}
        for _ in range(metadata_count):
            key = _string(source)
            metadata[key] = _value(source, GgufType(_scalar(source, "I")))
        metadata["inspection.tensor_count_not_loaded"] = tensor_count
        metadata["inspection.bytes_read_before_tensor_table"] = source.tell()
    return metadata


class _LlamaModelParams(ctypes.Structure):
    # ABI pinned to the header for llama.cpp b11963, used by Ollama v0.40.13.
    _fields_ = [
        ("devices", ctypes.c_void_p), ("tensor_buft_overrides", ctypes.c_void_p),
        ("n_gpu_layers", ctypes.c_int32), ("split_mode", ctypes.c_int),
        ("load_mode", ctypes.c_int), ("lazy_mode", ctypes.c_int), ("main_gpu", ctypes.c_int32),
        ("tensor_split", ctypes.c_void_p), ("progress_callback", ctypes.c_void_p),
        ("progress_callback_user_data", ctypes.c_void_p), ("kv_overrides", ctypes.c_void_p),
        ("vocab_only", ctypes.c_bool), ("check_tensors", ctypes.c_bool),
        ("use_extra_bufts", ctypes.c_bool), ("no_host", ctypes.c_bool),
        ("no_alloc", ctypes.c_bool), ("load_mtp", ctypes.c_bool),
    ]


class NativeQwenVocabulary:
    """No context creation, tensor evaluation, sampling, HTTP, or inference methods."""

    def __init__(
        self,
        library_directory: Path,
        model_path: Path,
        expected_library_sha256: str,
    ) -> None:
        if os.name != "nt" or ctypes.sizeof(_LlamaModelParams) != 80:
            raise ValueError("Unverified native ABI")
        if file_sha256(library_directory / "libllama.dll") != expected_library_sha256:
            raise ValueError("Unverified native library identity")
        self._directory = os.add_dll_directory(str(library_directory))
        self._library = ctypes.CDLL(str(library_directory / "libllama.dll"))
        self._configure_signatures()
        self.log: list[str] = []
        callback_type = ctypes.CFUNCTYPE(None, ctypes.c_int, ctypes.c_char_p, ctypes.c_void_p)
        self._null_log_callback = callback_type()
        self._log_callback = callback_type(lambda level, message, context: self.log.append(message.decode("utf-8")))
        self._library.llama_log_set.argtypes = [callback_type, ctypes.c_void_p]
        self._library.llama_log_set(self._log_callback, None)
        parameters = self._library.llama_model_default_params()
        parameters.vocab_only = True
        parameters.n_gpu_layers = 0
        parameters.use_extra_bufts = False
        self._model = self._library.llama_model_load_from_file(str(model_path).encode(), parameters)
        if not self._model:
            self.close()
            raise ValueError("Vocabulary-only loading failed")
        self._vocabulary = self._library.llama_model_get_vocab(self._model)
        if not self._vocabulary:
            self.close()
            raise ValueError("No native vocabulary")

    def _configure_signatures(self) -> None:
        signatures = {
            "llama_model_default_params": ([], _LlamaModelParams),
            "llama_model_load_from_file": ([ctypes.c_char_p, _LlamaModelParams], ctypes.c_void_p),
            "llama_model_get_vocab": ([ctypes.c_void_p], ctypes.c_void_p),
            "llama_model_free": ([ctypes.c_void_p], None),
            "llama_vocab_n_tokens": ([ctypes.c_void_p], ctypes.c_int32),
            "llama_vocab_get_text": ([ctypes.c_void_p, ctypes.c_int32], ctypes.c_char_p),
            "llama_vocab_get_attr": ([ctypes.c_void_p, ctypes.c_int32], ctypes.c_int),
            "llama_vocab_get_add_bos": ([ctypes.c_void_p], ctypes.c_bool),
            "llama_vocab_get_add_eos": ([ctypes.c_void_p], ctypes.c_bool),
            "llama_tokenize": ([ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int32,
                                ctypes.POINTER(ctypes.c_int32), ctypes.c_int32, ctypes.c_bool, ctypes.c_bool], ctypes.c_int32),
            "llama_detokenize": ([ctypes.c_void_p, ctypes.POINTER(ctypes.c_int32), ctypes.c_int32,
                                  ctypes.c_char_p, ctypes.c_int32, ctypes.c_bool, ctypes.c_bool], ctypes.c_int32),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self._library, name)
            function.argtypes = arguments
            function.restype = result

    def __enter__(self) -> NativeQwenVocabulary:
        return self

    def __exit__(self, *exception: object) -> None:
        self.close()

    def close(self) -> None:
        if getattr(self, "_model", None):
            self._library.llama_model_free(self._model)
            self._model = None
        self._library.llama_log_set(self._null_log_callback, None)
        if self._directory is not None:
            self._directory.close()
            self._directory = None

    def special_policy(self) -> dict[str, Any]:
        self._require_open()
        return {"add_bos": bool(self._library.llama_vocab_get_add_bos(self._vocabulary)),
                "add_eos": bool(self._library.llama_vocab_get_add_eos(self._vocabulary)),
                "vocabulary_size": self._library.llama_vocab_n_tokens(self._vocabulary)}

    def special_tokens(self) -> list[str]:
        self._require_open()
        count = self._library.llama_vocab_n_tokens(self._vocabulary)
        return [self._library.llama_vocab_get_text(self._vocabulary, identifier).decode("utf-8")
                for identifier in range(count)
                if self._library.llama_vocab_get_attr(self._vocabulary, identifier) & ((1 << 3) | (1 << 4))]

    def encode(self, prompt: str) -> list[int]:
        self._require_open()
        encoded = prompt.encode("utf-8")
        capacity = len(encoded) + 32
        tokens = (ctypes.c_int32 * capacity)()
        count = self._library.llama_tokenize(self._vocabulary, encoded, len(encoded), tokens, capacity, False, True)
        if count < 0 or count > capacity:
            raise ValueError("Native tokenizer could not return a complete token sequence")
        return list(tokens[:count])

    def decode(self, tokens: list[int], expected_utf8_bytes: int) -> bytes:
        self._require_open()
        identifiers = (ctypes.c_int32 * len(tokens))(*tokens)
        buffer = ctypes.create_string_buffer(expected_utf8_bytes + 1)
        length = self._library.llama_detokenize(self._vocabulary, identifiers, len(tokens), buffer,
                                                expected_utf8_bytes + 1, False, True)
        if length < 0 or length > expected_utf8_bytes:
            raise ValueError("Native detokenization did not preserve the full prompt")
        return buffer.raw[:length]

    def _require_open(self) -> None:
        if self._model is None:
            raise RuntimeError("The vocabulary has been closed")


def independent_byte_bpe(metadata: dict[str, Any], specials: list[str]) -> Any:
    from tokenizers import AddedToken, Regex, Tokenizer, decoders, models, pre_tokenizers

    if metadata.get("tokenizer.ggml.model") != "gpt2" or metadata.get("tokenizer.ggml.pre") != "qwen2":
        raise ValueError("Unverified independent tokenizer profile")
    vocabulary = {token: identifier for identifier, token in enumerate(metadata["tokenizer.ggml.tokens"])}
    merges = [tuple(merge.split(" ", 1)) for merge in metadata["tokenizer.ggml.merges"]]
    tokenizer = Tokenizer(models.BPE(vocab=vocabulary, merges=merges))
    pattern = r"(?i:'s|'t|'re|'ve|'m|'ll|'d)|[^\r\n\p{L}\p{N}]?\p{L}+|\p{N}| ?[^\s\p{L}\p{N}]+[\r\n]*|\s*[\r\n]+|\s+(?!\S)|\s+"
    tokenizer.pre_tokenizer = pre_tokenizers.Sequence([
        pre_tokenizers.Split(Regex(pattern), behavior="isolated"),
        pre_tokenizers.ByteLevel(add_prefix_space=False, use_regex=False),
    ])
    tokenizer.decoder = decoders.ByteLevel()
    tokenizer.add_special_tokens([AddedToken(token, special=True, normalized=False) for token in specials])
    return tokenizer
