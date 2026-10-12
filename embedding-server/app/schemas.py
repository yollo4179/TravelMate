from pydantic import BaseModel

class EmbeddingRequest(BaseModel):
    texts : list[str]

class EmbeddingResponse(BaseModel):
    embeddings :list[list[float]]

class RerankRequest(BaseModel):
    query: str
    texts: list[str]

class RerankResponse(BaseModel):
    scores: list[float]  # texts와 같은 순서, 정렬 안 된 원본 순서 그대로