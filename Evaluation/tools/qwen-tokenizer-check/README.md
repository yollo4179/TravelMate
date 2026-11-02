# Offline Qwen rendering/tokenization verification

This tool renders saved requests using `github.com/ollama/ollama/template@v0.40.13`.
It does not call a model or an application API. `main.go` reads JSONL on stdin and
returns the exact Go-rendered prompt, native request hash and prompt hash.

The Python verifier uses the installed Ollama `libllama.dll` vocabulary-only path,
with the ABI from Ollama's pinned llama.cpp `b11963`. It verifies the complete model
file hash and library hash before counting. It never creates a llama context,
loads model tensors, evaluates weights, samples, or calls `/api/chat`/`generate`.
Reading model bytes to verify their SHA-256 is separate from loading weights for inference.

An independent Rust `tokenizers` byte BPE is constructed from that GGUF's vocabulary
and merges, using the Qwen2 pre-tokenizer and native effective special tokens. Every
token ID must agree with native tokenization; decoding must reproduce all prompt bytes.
It does not use the model's embedded HF/Jinja chat template in place of Ollama's Go template.

The count is `EXACT_OFFLINE_CROSSCHECKED`, not API-reported usage. The runtime guard
does not import this tool and is unchanged. Support is restricted to the verified
Windows library/ABI and explicit `think=false`/`go_template` text requests.

Build in a local tool directory with Go 1.26.10; no global installation is required:

```powershell
# From this directory, using the explicitly selected Go executable and cache.
go mod download
go test -mod=readonly ./...
go build -mod=readonly -o <tool-directory>/render-qwen.exe .
```

The repository's optional Python dependency is `Evaluation/requirements/token-verification.txt`.
The actual verification reused the existing embedding-server environment; it did not
install or initialize transformers models.

From repository root, with `PYTHONPATH=Evaluation`:

```powershell
python -m tracks.tool_call.verify_qwen_tokens `
  --prior Evaluation/runs/contextual/model-evaluation-preparation-v1/20261101-01 `
  --saved-tool-events Evaluation/runs/contextual/token-budget-observation-v1/20261101-01/events.jsonl `
  --model <local-GGUF-path> --expected-model-sha256 <verified-model-digest> `
  --libraries <Ollama-library-directory> --expected-library-sha256 <verified-libllama-digest> `
  --renderer <tool-directory>/render-qwen.exe --expected-renderer-sha256 <verified-renderer-digest> `
  --output <new-output-directory>
```

Existing output directories are rejected. Native request hashes and template hashes
must equal the earlier budget audit. Unsupported inputs, missing files, identity
drift, native/HF ID differences or roundtrip differences fail explicitly. No fallback
to character ratios, prompt truncation or inference is available.

Sources: [Ollama template package](https://github.com/ollama/ollama/blob/v0.40.13/template/template.go),
[server prompt construction](https://github.com/ollama/ollama/blob/v0.40.13/server/prompt.go),
[runner tokenization](https://github.com/ollama/ollama/blob/v0.40.13/llm/llama_server.go),
[pinned native header](https://github.com/ggml-org/llama.cpp/blob/b11963/include/llama.h),
[Qwen2 native tokenizer rules](https://github.com/ggml-org/llama.cpp/blob/b11963/src/llama-vocab.cpp).
Upstream Go dependencies are imported under their original licenses; their versions
and checksum records are preserved in go.mod/go.sum. The native library remains in
the user's existing Ollama installation and is not redistributed.
