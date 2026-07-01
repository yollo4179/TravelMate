from fastapi import APIRouter
from app.schemas import EmbeddingRequest, EmbeddingResponse
from app.embedder import embedder

router = APIRouter()

@router.get("/health")
def health():
    return {"status": "ok", "dim": embedder.getDimension()}

@router.post("/embed", response_model=EmbeddingResponse)
def embed(req: EmbeddingRequest):
    return EmbeddingResponse(embeddings=embedder.embed(req.texts))