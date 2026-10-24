# 평가 자료 경로 변경

평가 자료는 [Evaluation/](../../Evaluation/README.md) 아래에서 버전별로 관리합니다.

- [v1.1.0](../../Evaluation/v1.1.0/README.md)
- [v1.2.0](../../Evaluation/v1.2.0/README.md)
- [v1.3.0 — 현재 검토 기준](../../Evaluation/v1.3.0/README.md)
- [메모가 채워진 리뷰 CSV](../../Evaluation/v1.3.0/review_notes_filled_v1.3.0.csv)
- [질문별 리뷰 설명](../../Evaluation/v1.3.0/review_notes_by_question.md)

기존 `run.sh`는 v1.3.0의 실행 파일로 연결합니다. 버전을 고정하려면 저장소 루트에서 다음 명령을 사용하세요.

```bash
bash Evaluation/v1.3.0/run.sh --check
bash Evaluation/v1.3.0/run.sh --test
```
