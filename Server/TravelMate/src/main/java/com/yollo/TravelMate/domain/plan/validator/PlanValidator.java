package com.yollo.TravelMate.domain.plan.validator;


import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;

@Component 
public class PlanValidator {

    private static final Logger log = LoggerFactory.getLogger(PlanValidator.class);
    private final ObjectMapper objectMapper = new ObjectMapper();

    /**
     * LLM 원본 출력 → 정제 → 파싱 → 검증된 GeneratedPlan.
     * @param rawOutput   LLM이 뱉은 원본 문자열
     * @param validIds    검색 후보의 placeId 집합 (환각 최종 차단용)
     */
    public GeneratedPlan validate(String rawOutput, Set<Long> validIds) {
        // 1) 정제 — 코드블록·앞뒤 잡텍스트 제거, JSON 부분만 추출
        String cleaned = extractJson(rawOutput);

        // 2) 파싱
        GeneratedPlan plan;
        try {
            plan = objectMapper.readValue(cleaned, GeneratedPlan.class); //tojson
        } catch (Exception e) {
            log.error("JSON 파싱 실패. 원본: {}", rawOutput);
            throw new ErrorCodeException(ErrorCode.PLAN_LLM_PARSE_FAILED);
        }

        // 3) 검증
        if (plan.pins() == null || plan.pins().isEmpty()) {
        	 throw new ErrorCodeException(ErrorCode.PLAN_EMPTY_PINS);
        }

        // 3-1) 환각 최종 차단 — 후보에 없는 placeId 제거
        List<GeneratedPlan.GeneratedPin> validPins = plan.pins().stream()
                .filter(pin -> {
                    if (pin.placeId() == null || !validIds.contains(pin.placeId())) {
                        log.warn("후보 밖 placeId 제거(환각): {}", pin.placeId());
                        return false;
                    }
                    return true;
                })
                .collect(Collectors.toList());

        if (validPins.isEmpty()) {
        	 throw new ErrorCodeException(ErrorCode.PLAN_ALL_HALLUCINATED);
        }

        return new GeneratedPlan(plan.planTitle(), plan.planDescription(), validPins);
    }

    /** 코드블록 마커·앞뒤 텍스트를 걷어내고 JSON 본문만 추출 */
    private String extractJson(String raw) {
    	 if (raw == null) throw new ErrorCodeException(ErrorCode.PLAN_LLM_PARSE_FAILED);
        String s = raw.trim();

        // 제이슨 백틱 래핑 좌우 제거 : ```json ... ``` 또는 ``` ... ``` 제거
        s = s.replaceAll("(?s)```(?:json)?", "").trim();

        
        
        // 첫 '{' 부터 마지막 '}' 까지만 (앞뒤 설명 문장 제거)
        int start = s.indexOf('{');
        int end = s.lastIndexOf('}');
        if (start == -1 || end == -1 || start > end) {
        	 throw new ErrorCodeException(ErrorCode.PLAN_LLM_PARSE_FAILED);
        }
        return s.substring(start, end + 1);
    }
}