from fastapi import APIRouter
from app.schemas import RerankRequest, RerankResponse
from app.reranker import reranker
from app.observability import tracer

router = APIRouter()

@router.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest) -> RerankResponse:
    with tracer().start_as_current_span("reranking.model_inference") as span:
        span.set_attribute("reranking.device", reranker.device)
        span.set_attribute("reranking.candidate_count", len(req.texts))
        scores = reranker.rerank(req.query, req.texts)
        span.set_attribute("reranking.score_count", len(scores))
        return RerankResponse(scores=scores)
