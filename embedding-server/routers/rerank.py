from fastapi import APIRouter
from app.schemas import RerankRequest, RerankResponse
from app.reranker import reranker

router = APIRouter()

@router.post("/rerank", response_model=RerankResponse)
def rerank(req: RerankRequest):
    return RerankResponse(scores=reranker.rerank(req.query, req.texts))
