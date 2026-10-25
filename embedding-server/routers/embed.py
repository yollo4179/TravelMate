from fastapi import APIRouter, Request
from app.schemas import EmbeddingRequest, EmbeddingResponse
from app.embedder import embedder
from app.observability import tracer
from app.device import get_cuda_status
from app.reranker import reranker

router = APIRouter()

@router.get("/health")
async def health(request: Request) -> dict[str, int | str | bool]:
    cuda_available, gpu_name = get_cuda_status()
    device_status = {
        "embedding_device": embedder.device,
        "reranker_device": reranker.device,
        "cuda_available": cuda_available,
        "gpu_name": gpu_name,
    }
    database_pool = getattr(request.app.state, "database_pool", None)
    kafka_runtime = getattr(request.app.state, "kafka_runtime", None)
    if database_pool is None or kafka_runtime is None:
        return {"status": "not_ready", "dim": embedder.getDimension(), **device_status}
    try:
        await database_pool.fetchval("SELECT 1")
    except Exception:
        return {"status": "not_ready", "dim": embedder.getDimension(), **device_status}
    if any(task.done() for task in kafka_runtime.tasks):
        return {"status": "not_ready", "dim": embedder.getDimension(), **device_status}
    return {"status": "ok", "dim": embedder.getDimension(), **device_status}

@router.post("/embed", response_model=EmbeddingResponse)
def embed(req: EmbeddingRequest) -> EmbeddingResponse:
    with tracer().start_as_current_span("embedding.model_inference") as span:
        span.set_attribute("embedding.text_count", len(req.texts))
        span.set_attribute("embedding.device", embedder.device)
        embeddings = embedder.embed(req.texts)
        span.set_attribute("embedding.dimension", embedder.getDimension())
        return EmbeddingResponse(embeddings=embeddings)
