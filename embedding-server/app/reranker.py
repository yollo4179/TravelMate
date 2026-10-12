import torch
from sentence_transformers import CrossEncoder
from app.config import MODEL_NAME_RERANKER, MODEL_DEVICE_RERANKER

class Reranker:
    def __init__(self):
        device = MODEL_DEVICE_RERANKER
        if device == "cuda" and not torch.cuda.is_available():
            print("[Reranker] CUDA unavailable, falling back to CPU")
            device = "cpu"

        print(f"[Reranker] 모델 로딩 중: {MODEL_NAME_RERANKER} (device={device})")
        self.model = CrossEncoder(MODEL_NAME_RERANKER, device=device)
        print("[Reranker] 로딩 완료.")

    # 쿼리 하나 vs 후보 텍스트 여러 개 -> 관련도 점수 리스트 (후보 순서 그대로, 정렬은 호출부에서)
    def rerank(self, query: str, texts: list[str]) -> list[float]:
        pairs = [[query, t] for t in texts]
        scores = self.model.predict(pairs)
        return scores.tolist()

reranker = Reranker()  # static 입니다.
