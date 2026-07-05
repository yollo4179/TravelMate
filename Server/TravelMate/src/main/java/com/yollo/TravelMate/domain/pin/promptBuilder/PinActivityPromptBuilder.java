package com.yollo.TravelMate.domain.pin.promptBuilder;



import java.util.List;
import java.util.Map;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;

import com.fasterxml.jackson.databind.JsonNode;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository.ProgramInsert;


public class PinActivityPromptBuilder {
 
    private static final Logger log = LoggerFactory.getLogger(PinActivityPromptBuilder.class);
    private static final ObjectMapper MAPPER = new ObjectMapper();
 
    /**
     * detailIntro1의 알려진 필드 키 → 한글 라벨 매핑.
     * contentTypeId(8종)별로 필드셋이 다르지만, 뜻을 아는 키만 골라 자연어화하므로
     * 타입별 분기 없이 이 맵 하나로 커버한다. 맵에 없는 키는 무시(LLM 오독 방지).
     */
    private static final Map<String, String> FIELD_LABELS = Map.ofEntries(
        Map.entry("usetime", "이용시간"),
        Map.entry("restdate", "휴무일"),
        Map.entry("usefee", "이용요금"),
        Map.entry("infocenter", "문의처"),
        Map.entry("parking", "주차 정보"),
        Map.entry("playtime", "관람 소요시간"),
        Map.entry("opentimefood", "영업시간"),
        Map.entry("restdatefood", "휴무일"),
        Map.entry("firstmenu", "대표메뉴"),
        Map.entry("treatmenu", "취급메뉴"),
        Map.entry("checkintime", "체크인 시간"),
        Map.entry("checkouttime", "체크아웃 시간"),
        Map.entry("scale", "규모")
    );
 
    private PinActivityPromptBuilder() {}
 
    public static String build(String rawIntroJson, List<ProgramInsert> programs,
                                String planTitle, String pacePreference) {
        StringBuilder sb = new StringBuilder();
 
        sb.append("[장소 정보]\n");
        String introText = extractKnownFields(rawIntroJson); //Text로 추출합니다. (판단 요소들)Rag 제공(TourAPI)
        sb.append(!introText.isBlank() ? introText : "운영정보: 확인된 정보 없음\n");
 
        if (programs != null && !programs.isEmpty()) {
            StringBuilder programText = new StringBuilder();
            for (ProgramInsert p : programs) {
                if (p.infoText() != null && !p.infoText().isBlank()) {
                    programText.append("- ")
                               .append(p.infoName() != null ? p.infoName() : "안내")
                               .append(": ").append(p.infoText()).append("\n");
                }
            }
            if (programText.length() > 0) {
                sb.append("체험 프로그램:\n").append(programText);
            } else {
                // programs 리스트는 있으나 infoText가 전부 비어있는 경우 → 사실상 GENERIC
                sb.append("체험 프로그램: 확인된 정보 없음\n");
            }
        } else {
            sb.append("체험 프로그램: 확인된 정보 없음\n");
        }
 
        sb.append("\n[상위 계획 맥락]\n여행 테마: ")
          .append(planTitle != null ? planTitle : "명시 안 함").append("\n");
 
        sb.append("\n[사용자 선호]\n여행 강도: ")
          .append(pacePreference != null ? pacePreference : "명시 안 함").append("\n");
 
        return sb.toString();
    }
 
    /** 알려진 필드 키만 추출해 한글 라벨로 변환. 모르는 필드는 무시. */
    private static String extractKnownFields(String rawIntroJson) {
        if (rawIntroJson == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        try {
            JsonNode node = MAPPER.readTree(rawIntroJson);
            for (Map.Entry<String, String> entry : FIELD_LABELS.entrySet()) {
                JsonNode value = node.path(entry.getKey());
                if (!value.isMissingNode() && value.asText() != null && !value.asText().isBlank()) {
                    sb.append(entry.getValue()).append(": ").append(value.asText().trim()).append("\n");
                }
            }
        } catch (Exception e) {
            log.warn("place_details raw_intro 파싱 실패, 운영정보 없이 진행합니다.", e);
            return "";
        }
        return sb.toString();
    }
}