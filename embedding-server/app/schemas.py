from pydantic import BaseModel


class EmbeddingRequest(BaseModel):
    texts: list[str]


class EmbeddingResponse(BaseModel):
    embeddings: list[list[float]]


class RerankRequest(BaseModel):
    query: str
    texts: list[str]


class RerankResponse(BaseModel):
    scores: list[float]
