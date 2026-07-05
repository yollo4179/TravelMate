package com.yollo.TravelMate.domain.pin.validator;


import java.util.List;
import java.util.stream.Collectors;
 
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
 
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.pin.data.internal.GeneratedPinActivities;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;
 
@Component
public class PinActivityValidator {
 
    private static final Logger log = LoggerFactory.getLogger(PinActivityValidator.class);
    private static final int GENERIC_MAX_ACTIVITIES = 2;
 
    private final ObjectMapper objectMapper = new ObjectMapper();
 
    /**
     * LLM 원본 출력 → 정제 → 파싱 → 검증된 GeneratedPinActivities.
     *
     * @param rawOutput     LLM이 뱉은 원본 문자열
     * @param expectedPinId 우리가 실제로 요청한 pinId (응답의 pinId와 일치해야 함)
     * @param hadPrograms   place_programs 존재 여부 (모드 교차검증용)
     *                      true  → GROUNDED 모드로 응답해야 정상
     *                      false → GENERIC 모드로 응답해야 정상. GROUNDED면 창작 의심 → 거부
     */
    public GeneratedPinActivities validate(String rawOutput, Long expectedPinId, boolean hadPrograms) {
        String cleaned = extractJson(rawOutput);
 
        GeneratedPinActivities result;
        try {
            result = objectMapper.readValue(cleaned, GeneratedPinActivities.class);
        } catch (Exception e) {
            log.error("JSON 파싱 실패. 원본: {}", rawOutput);
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_LLM_PARSE_FAILED);
        }
 
        // 1) pinId 불일치 방어
        if (result.pinId() == null || !result.pinId().equals(expectedPinId)) {
            log.warn("LLM 응답 pinId 불일치: expected={}, actual={}", expectedPinId, result.pinId());
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_PIN_MISMATCH);
        }
 
        // 2) 비어있음 방어
        if (result.activities() == null || result.activities().isEmpty()) {
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_EMPTY);
        }
 
        // 3) 모드 교차검증 — programs 없는데 GROUNDED = 없는 근거를 지어냈다는 강한 신호 → 거부
        if (!hadPrograms && "GROUNDED".equals(result.mode())) {
            log.warn("programs 없으나 GROUNDED 응답(창작 의심), 거부합니다: pinId={}", expectedPinId);
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_HALLUCINATION_SUSPECTED);
        }
        // programs 있는데 GENERIC = 자료를 무시함. 거부까진 아니고 경고만 (내용 창작 위험은 낮음)
        if (hadPrograms && "GENERIC".equals(result.mode())) {
            log.warn("programs 존재하나 GENERIC 응답(자료 미활용): pinId={}", expectedPinId);
        }
 
        // 4) 형식 요건 미달 항목 제거
        List<GeneratedPinActivities.GeneratedActivity> validActivities = result.activities().stream()
                .filter(a -> {
                    if (a.activity() == null || a.activity().isBlank() || a.sequence() == null) {
                        log.warn("형식 미달 activity 제거: {}", a);
                        return false;
                    }
                    return true;
                })
                .collect(Collectors.toList());
 
        if (validActivities.isEmpty()) {
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_EMPTY);
        }
 
        // 5) GENERIC 모드 활동 개수 하드 캡 — 정보 없는데 많이 쪼개면 창작 확률↑
        boolean isGeneric = !hadPrograms || "GENERIC".equals(result.mode());
        if (isGeneric && validActivities.size() > GENERIC_MAX_ACTIVITIES) {
            log.warn("GENERIC 모드 활동 {}개 → 상위 {}개로 절삭: pinId={}",
                    validActivities.size(), GENERIC_MAX_ACTIVITIES, expectedPinId);
            validActivities = validActivities.subList(0, GENERIC_MAX_ACTIVITIES);
        }
 
        return new GeneratedPinActivities(expectedPinId, result.mode(), validActivities);
    }
 
    /** 코드블록 마커·앞뒤 텍스트를 걷어내고 JSON 본문만 추출 (PlanValidator와 동일 로직) */
    private String extractJson(String raw) {
        if (raw == null) throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_LLM_PARSE_FAILED);
        String s = raw.trim();
        s = s.replaceAll("(?s)```(?:json)?", "").trim();
 
        int start = s.indexOf('{');
        int end = s.lastIndexOf('}');
        if (start == -1 || end == -1 || start > end) {
            throw new ErrorCodeException(ErrorCode.PIN_ACTIVITY_LLM_PARSE_FAILED);
        }
        return s.substring(start, end + 1);
    }
}