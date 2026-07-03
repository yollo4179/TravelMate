package com.yollo.TravelMate.domain.place.formatter;

import java.util.List;

import com.yollo.TravelMate.domain.place.data.result.PlaceResult;

public final class CandidateFormatter {

    private CandidateFormatter() {}

    /**
     * 검색 결과를 LLM 프롬프트용 텍스트로 변환.
     * category는 오염 가능성이 있어 제외, description은 reason 근거로 포함.
     */
    public static String format(List<PlaceResult> candidates) {
        StringBuilder sb = new StringBuilder();
        for (PlaceResult p : candidates) {
            sb.append("[placeId=").append(p.id()).append("] ")
              .append(p.name())
              .append(" | 설명: ").append(p.description())
              .append(" | 위치: ").append(p.region());
            if (p.city() != null && !p.city().equals(p.region())) {
                sb.append(" ").append(p.city());
            }
            sb.append(" (").append(p.latitude()).append(", ").append(p.longitude()).append(")")
              .append("\n");
        }
        return sb.toString();
    }
}