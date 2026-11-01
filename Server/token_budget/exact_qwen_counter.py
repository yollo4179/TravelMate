"""One-request vocabulary-only worker. Stdin is the complete captured native request."""
from __future__ import annotations

import argparse
import hashlib
import json
import importlib.metadata
from pathlib import Path
import struct
import subprocess
import sys
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from Server.token_budget.qwen_tokenization import NativeQwenVocabulary, file_sha256, independent_byte_bpe, read_gguf_metadata

MODEL_DIGEST = "500a1f067a9f782620b40bee6f7b0c89e17ae61f686b92c24933e4ca4b2b8b41"
MODEL_SHA256 = "a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f"
LIBRARY_SHA256 = "a9ccb9ae84f200579d1103a6d7cb67eb2e79342961497a74dc35d9c87894d9d9"
RENDERER_SHA256 = "cec56cb03f8670a9b2e53b01cca20068b1cdad6f611bb7cb18663f8a2bfd5027"
TEMPLATE_SHA256 = "ae370d884f108d16e7cc8fd5259ebc5773a0afa6e078b11f4ed7e39a27e0dfc4"


def digest(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def validate_identity(envelope: dict[str, Any]) -> dict[str, Any]:
    wire = envelope["wire"]
    request = json.loads(wire)
    show = envelope["show"]
    models = [model for model in envelope["tags"].get("models", []) if model.get("name") == request["model"]]
    if (envelope["version"].get("version") != "0.40.13" or request["model"] != "qwen3:8b"
            or len(models) != 1 or models[0].get("digest") != MODEL_DIGEST):
        raise ValueError("Unsupported server or model identity")
    info = show.get("model_info", {})
    if (show.get("template_source") != "go_template" or show.get("system")
            or digest(show.get("template", "")) != TEMPLATE_SHA256
            or info.get("general.architecture") != "qwen3"
            or info.get("tokenizer.ggml.model") != "gpt2" or info.get("tokenizer.ggml.pre") != "qwen2"
            or info.get("qwen3.context_length") != 40960):
        raise ValueError("Unsupported template or tokenizer identity")
    allowed = {"model", "think", "stream", "messages", "options", "format", "tools"}
    if (set(request) - allowed or request.get("think") is not False or request.get("stream") is not False
            or not isinstance(request.get("messages"), list)
            or request.get("format", "json") != "json"
            or set(request.get("options", {})) != {"temperature", "num_ctx", "num_predict"}):
        raise ValueError("Unsupported request shape")
    for message in request["messages"]:
        if (set(message) - {"role", "content", "tool_calls", "tool_name"}
                or message.get("role") not in {"system", "user", "assistant", "tool"}
                or not isinstance(message.get("content"), str)):
            raise ValueError("Unsupported message shape")
    return request


def count(envelope: dict[str, Any], profile: dict[str, str]) -> dict[str, Any]:
    validate_identity(envelope)
    if importlib.metadata.version("tokenizers") != "0.22.2":
        raise ValueError("Unsupported independent tokenizer version")
    model = Path(profile["model_path"])
    renderer = Path(profile["renderer_path"])
    libraries = Path(profile["library_directory"])
    manifest = Path(profile["manifest_path"])
    if (file_sha256(manifest) != MODEL_DIGEST or file_sha256(model) != MODEL_SHA256
            or file_sha256(renderer) != RENDERER_SHA256):
        raise ValueError("Local manifest, model or renderer identity mismatch")
    manifest_document = json.loads(manifest.read_bytes())
    if not any(layer.get("digest") == "sha256:" + MODEL_SHA256 for layer in manifest_document["layers"]):
        raise ValueError("Manifest does not identify the counted model")
    metadata = read_gguf_metadata(model)
    if (metadata.get("general.architecture") != "qwen3" or metadata.get("tokenizer.ggml.model") != "gpt2"
            or metadata.get("tokenizer.ggml.pre") != "qwen2" or metadata.get("qwen3.context_length") != 40960):
        raise ValueError("Unsupported local GGUF tokenizer")
    # Preserve the JVM's exact serialized wire bytes inside the renderer envelope.
    render_input = ('{"key":"runtime","wire":' + envelope["wire"] + ',"template":'
                    + json.dumps(envelope["show"]["template"], ensure_ascii=False)
                    + ',"template_source":"go_template"}\n')
    rendered_process = subprocess.run([str(renderer.resolve())], input=render_input.encode(),
                                      capture_output=True, check=True, timeout=30)
    rendered = json.loads(rendered_process.stdout)
    if rendered["wire_sha256"] != digest(envelope["wire"]) or rendered["template_sha256"] != TEMPLATE_SHA256:
        raise ValueError("Rendered input identity mismatch")
    prompt = rendered["prompt"]
    if digest(prompt) != rendered["prompt_sha256"]:
        raise ValueError("Rendered prompt identity mismatch")
    with NativeQwenVocabulary(libraries, model, LIBRARY_SHA256) as native:
        policy = native.special_policy()
        if policy != {"add_bos": False, "add_eos": False, "vocabulary_size": 151936}:
            raise ValueError("Unsupported special token policy")
        identifiers = native.encode(prompt)
        independent = independent_byte_bpe(metadata, native.special_tokens())
        if (identifiers != independent.encode(prompt, add_special_tokens=False).ids
                or native.decode(identifiers, len(prompt.encode())) != prompt.encode()):
            raise ValueError("Tokenizer cross-check or complete prompt roundtrip failed")
    return {"inputTokens": len(identifiers), "wireSha256": digest(envelope["wire"]),
            "templateSha256": TEMPLATE_SHA256, "promptSha256": digest(prompt),
            "tokenIdsSha256": hashlib.sha256(struct.pack("<" + str(len(identifiers)) + "i", *identifiers)).hexdigest(),
            "modelDigest": MODEL_DIGEST, "modelSha256": MODEL_SHA256,
            "librarySha256": LIBRARY_SHA256, "rendererSha256": RENDERER_SHA256,
            "serverVersion": "0.40.13", "nativeContextTokens": 40960,
            "quality": "EXACT_LOCAL_CROSSCHECKED", "tokenizer": "gpt2/qwen2;b11963;tokenizers=0.22.2",
            "inferenceDispatched": False}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", required=True, type=Path)
    arguments = parser.parse_args()
    sys.stdin.reconfigure(encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    envelope = json.load(sys.stdin)
    profile = json.loads(arguments.profile.read_text(encoding="utf-8"))
    print(json.dumps(count(envelope, profile), ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception as exception:
        print("Exact token accounting failed: " + type(exception).__name__, file=sys.stderr)
        sys.exit(1)
