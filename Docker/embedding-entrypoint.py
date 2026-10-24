"""Container runtime overrides without modifying the repository's embedding app."""
import hashlib
import os
from pathlib import Path

import uvicorn
from huggingface_hub import snapshot_download

import app.config as config

# The original config pins CUDA. Containers default to CPU on non-GPU machines.
config.MODEL_DEVICE_EMBEDDING = os.environ.get("EMBEDDING_DEVICE", "cpu")
config.MODEL_NAME_EMBEDDING = os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3")

if __name__ == "__main__":
    revision = os.environ.get("EMBEDDING_REVISION")
    if revision:
        # Pin the official model snapshot and download only SentenceTransformer files.
        local_model = Path(snapshot_download(
            repo_id=config.MODEL_NAME_EMBEDDING,
            revision=revision,
            allow_patterns=['*.json', '*.txt', '*.model', '*.bin', '1_Pooling/*'],
            ignore_patterns=['onnx/*'],
        ))
        expected = os.environ.get("EMBEDDING_WEIGHTS_SHA256")
        if expected:
            digest = hashlib.sha256()
            with (local_model / 'pytorch_model.bin').open('rb') as weights:
                for chunk in iter(lambda: weights.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)
            if digest.hexdigest() != expected:
                raise RuntimeError('Embedding model SHA-256 verification failed')
            print('Embedding model SHA-256 verification passed', flush=True)
        config.MODEL_NAME_EMBEDDING = str(local_model)
    # One worker loads one model. Multiple workers duplicate model memory.
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, workers=1)
