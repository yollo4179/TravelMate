# 이동 전용 정규식 정책: 오프라인 실험

`87e06d3e`에서 일반 검색에 적용했던 질문 분류·강제 보류·설명 교체 정책을 보존한다.
현재 서비스 앱은 이 패키지를 import하지 않는다. 운영 환경 변수나 요청 옵션으로 활성화할 수 없다.
서비스의 원문·관계·출처 검사와 이 정규식 의미 추정을 혼동하지 않는다.

명시적인 실험 선택이 있어야 과거 정책 재생을 실행할 수 있다.

```powershell
python -X utf8 Evaluation/tracks/contextual/evidence_quality_replay.py --experimental-policy movement-regex-v1 --archive-root <로컬-보존-아카이브> --output <새-실험-폴더>
python -X utf8 -m unittest Evaluation.tracks.contextual.experiments.connection_quality.test_policy
```

원본 저장 자료만 사용하며 실제 검색·모델·DB를 호출하지 않는다. 과거 규칙의 성공/차단 라벨은 정규식 추정일 뿐
의미 함의 정답이나 현재 통행 상태가 아니다. 단위 검증은 과거 규칙의 재현성을 검사하며 일반 검색 품질의 인증이 아니다.
일반 검색의 회귀 검증은 `test_contextual_general_search_contract.py`와 별도 저장 결과 비교를 사용한다.
