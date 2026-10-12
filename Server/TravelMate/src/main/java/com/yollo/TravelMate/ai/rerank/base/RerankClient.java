package com.yollo.TravelMate.ai.rerank.base;

import java.util.List;
import java.util.function.Function;

public interface RerankClient {

	/**
	 * 후보 레코드 리스트를 받아 재랭킹하고 (레코드, 점수) 쌍으로 묶어 점수 내림차순으로 반환한다.
	 * textOf로 각 레코드에서 재랭킹용 텍스트만 뽑아 전송하고(HTTP로는 텍스트만 오감,
	 * 파이썬 서버가 도메인 모델을 알 필요 없음), 응답으로 받은 점수는 여기서 바로 원래 레코드와
	 * 짝지어서 반환한다 - 호출부가 인덱스로 직접 매칭할 필요가 없어 순서 꼬임 위험이 없다.
	 */
	<T> List<Scored<T>> rerank(String query, List<T> candidates, Function<T, String> textOf);

	record Scored<T>(T candidate, float score) {}
}
