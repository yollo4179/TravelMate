"""Shared production/evaluation model settings; connection profiles do not fork code."""
import os

MODEL_NAME_EMBEDDING = os.environ.get("MODEL_NAME_EMBEDDING", os.environ.get("EMBEDDING_MODEL", "BAAI/bge-m3"))
MODEL_DEVICE_EMBEDDING = os.environ.get("MODEL_DEVICE_EMBEDDING", os.environ.get("EMBEDDING_DEVICE", "cuda"))
MODEL_NAME_RERANKER = os.environ.get("MODEL_NAME_RERANKER", "BAAI/bge-reranker-v2-m3")
MODEL_DEVICE_RERANKER = os.environ.get("MODEL_DEVICE_RERANKER", os.environ.get("RERANKER_DEVICE", "cuda"))
PORT = int(os.environ.get("PORT", "8000"))
