# 사람 질문 검수를 반영한 검색 평가셋 search-holdout-v1.0.1

원본 [search-holdout-v1.0.0](../search-holdout-v1.0.0/README.md)의 질문 검수를 반영했다.
총 73문항이며 구성은 `{'primary': 60, 'challenge': 13}`다.
제외 문항과 원래 검수표는 `source/review_changes.json`과 `source/original_question_review.csv`에 보존했다.
문항을 임의로 승인하거나 문장을 수정하지 않았다. 장소 적합도 판정은 아직 하지 않았다.

조용한 곳·여유로운 산책처럼 주관적이지만 자연스러운 질문도 유지한다.
소음·혼잡도 근거가 부족하면 장소 판정에서 unknown으로 남기며 질문을 억지로 구체화하지 않는다.

원본 안내의 명령에는 반드시 이 디렉터리를 `--dataset`으로 지정한다.
수집 시 `--question-review`에는 이 버전의 `source/question_review.csv`를 사용한다.
모델·배치 설정과 동결 코퍼스는 원본 프로토콜을 유지한다.

공란이었던 4문항은 사용자의 명시적인 채팅 지시로 accept 처리했다.
해당 행의 reviewer는 `user_chat_instruction`이며 기존 76개 판정과 원문은 변경하지 않았다.
기본 60문항과 도전 13문항 중, 도전 문항은 근거 민감 조건 10개와 국내 다른 지역 요청 3개다.

검수 단계에서는 `candidates.csv`의 질문·장소 설명을 읽고 `rubric.md`에 따라 적합도를 판정한다.
검색 방식·원래 순위·점수는 검수표에 공개하지 않는다. 근거가 부족하면 unknown으로 남긴다.
질문의 자연스러운 주관적 표현을 다시 작성하거나 기존 질문의 정답을 복사하지 않는다.
