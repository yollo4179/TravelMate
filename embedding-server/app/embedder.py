from sentence_transformers import SentenceTransformer
from app.config import MODEL_NAME_EMBEDDING, MODEL_DEVICE_EMBEDDING

class Embedder :
    # 생성자
    def __init__(self):
        # 모델 (멤버)
        print(f"[Embedder] 모델 로딩 중: {MODEL_NAME_EMBEDDING} (device={MODEL_DEVICE_EMBEDDING})")
        self.model = SentenceTransformer(
            model_name_or_path=MODEL_NAME_EMBEDDING,
            device=MODEL_DEVICE_EMBEDDING
        )
        print(f"[Embedder] 로딩 완료. 차원={self.getDimension()}")
    
    # To Vector
    def embed(self, texts:  list[str]) -> list[list[float]]:
        # 내적을 이용한 유사도 계산을 위해 정규화 
        # ( 방향 일치가 유사도의 기준 크기가 다르다면 유사도 계산이 안됨 )
        # 사실 벡터의 크기는 정보의 밀도(확실하고 중요할수록 크기가 큼)
        #학습 데이터셋에서 특정 단어나 문맥이 자주 등장하거나 강한 연관성을 가질 경우, 모델은 해당 문장의 벡터 값을 더 크게 출력
        #벡터의 크기(길이)가 의미상 "중요도"를 뜻한다고 하더라도,공정한 비교를위해 정규화 )
        # 유사도가 높은데도 크기가 작다는 이유로 순위에서 밀려날 수 있습니다.
        vectors=  self.model.encode(texts, normalize_embeddings=True)
        return vectors.tolist()

    def getDimension(self):
        return self.model.get_sentence_embedding_dimension() 
embedder = Embedder()# static 입니다.