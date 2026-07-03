package com.yollo.TravelMate.domain.plan.service;

import java.util.List;
import java.util.Set;
import java.util.stream.Collectors;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import com.yollo.TravelMate.ai.embedding.base.EmbeddingClient;
import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.domain.place.data.result.PlaceResult;
import com.yollo.TravelMate.domain.place.formatter.CandidateFormatter;
import com.yollo.TravelMate.domain.place.repository.PlaceVectorRepository;
import com.yollo.TravelMate.domain.plan.data.internal.GeneratedPlan;
import com.yollo.TravelMate.domain.plan.prompts.PlanPrompts;
import com.yollo.TravelMate.domain.plan.repository.PlanRepository;
import com.yollo.TravelMate.domain.plan.validator.PlanValidator;
import com.yollo.TravelMate.exceptions.cumtom.ErrorCodeException;
import com.yollo.TravelMate.exceptions.errorCodes.ErrorCode;

import jakarta.transaction.Transactional;
import lombok.RequiredArgsConstructor;

@Service
@RequiredArgsConstructor
public class PlanGenerationService {
	private static final Logger log = LoggerFactory.getLogger(PlanGenerationService.class);

    private final EmbeddingClient embeddingClient;
    private final PlaceVectorRepository placeRepository;
    private final LlmClient llmClient;

    private final  PlanRepository planRepository;
    private final PlanValidator planValidator;
    
    
    /**
     * 관문4 MVP: 요청 → 임베딩 → 검색 → 후보주입 → LLM 플랜 생성.
     * (저장·Validator는 다음 단계)
     */
    public String generatePlanRaw(String userRequest, String region) {
        // [1] 요청 임베딩
        float[] queryVec = embeddingClient.embed(userRequest);

        // [2] 벡터 검색으로 실재 후보 확보
        List<PlaceResult> candidates =
                placeRepository.searchSimilar(queryVec, region, null, null, 0.3, 10);

        if (candidates.isEmpty()) {
            log.warn("검색 후보 없음: {} (region={})", userRequest, region);
            return "{\"planTitle\":\"\",\"pins\":[]}";
        }

        // [3] 후보를 프롬프트 텍스트로
        String candidatesText = CandidateFormatter.format(candidates);

        // [4] userPrompt 조립
        String userPrompt = """
                여행 요청: %s

                장소 후보:
                %s
                위 후보 중에서 요청에 맞는 장소를 선별하여 일정을 구성하라.
                """.formatted(userRequest, candidatesText);

        log.info("=== 후보 {}곳으로 플랜 생성 요청 ===", candidates.size());

        // [5] LLM 호출
        return llmClient.generate(PlanPrompts.PLANNER_SYSTEM, userPrompt);
    }
    
    @Transactional
    public Long generateAndSave(String userRequest, String region, String userUid) {
        float[] queryVec = embeddingClient.embed(userRequest);
        List<PlaceResult> candidates =
                placeRepository.searchSimilar(queryVec, region, null, null, 0.3, 10);
        if (candidates.isEmpty()) {
            throw new ErrorCodeException(ErrorCode.PLAN_NO_CANDIDATES);
        }

        String candidatesText = CandidateFormatter.format(candidates);
        String userPrompt = "여행 요청: %s\n\n장소 후보:\n%s\n위 후보 중에서 일정을 구성하라."
                .formatted(userRequest, candidatesText);
        String raw = llmClient.generate(PlanPrompts.PLANNER_SYSTEM, userPrompt);

        Set<Long> validIds = candidates.stream()
                .map(PlaceResult::id).collect(Collectors.toSet());
        GeneratedPlan plan = planValidator.validate(raw, validIds);

        return planRepository.saveDraft(plan, candidates, userUid);
    }
}
