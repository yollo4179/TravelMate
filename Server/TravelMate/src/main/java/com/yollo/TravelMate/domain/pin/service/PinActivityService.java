package com.yollo.TravelMate.domain.pin.service;
 
import java.util.List;
 
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

import com.yollo.TravelMate.ai.llm.base.LlmClient;
import com.yollo.TravelMate.domain.pin.data.internal.GeneratedPinActivities;
import com.yollo.TravelMate.domain.pin.promptBuilder.PinActivityPromptBuilder;
import com.yollo.TravelMate.domain.pin.prompts.PinActivityPrompts;
import com.yollo.TravelMate.domain.pin.repository.PinActivityRepository;
import com.yollo.TravelMate.domain.pin.validator.PinActivityValidator;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository;
import com.yollo.TravelMate.domain.tourAPI.repository.PlaceDetailRepository.ProgramInsert;
import com.yollo.TravelMate.domain.tourAPI.service.PlaceDetailSyncService;
 

@Service
public class PinActivityService {
 
    private static final Logger log = LoggerFactory.getLogger(PinActivityService.class);
 
    private final PlaceDetailRepository placeDetailRepository;
    private final PlaceDetailSyncService placeDetailSyncService;
    private final PinActivityValidator pinActivityValidator;
    private final PinActivityRepository pinActivityRepository;
    private final LlmClient llmClient;
 
    public PinActivityService(
            PlaceDetailRepository placeDetailRepository,
            PlaceDetailSyncService placeDetailSyncService,
            PinActivityValidator pinActivityValidator,
            PinActivityRepository pinActivityRepository,
            LlmClient llmClient) {
        this.placeDetailRepository = placeDetailRepository;
        this.placeDetailSyncService = placeDetailSyncService;
        this.pinActivityValidator = pinActivityValidator;
        this.pinActivityRepository = pinActivityRepository;
        this.llmClient = llmClient;
    }
 
    /**
     * 핀 상세 활동(극소 계획)을 생성해 SUGGESTED 상태로 저장합니다.
     * place_details 캐시가 없으면 TourAPI를 최초 1회 호출합니다 (on-demand).
     * place_programs 존재 여부(hadPrograms)로 GROUNDED/GENERIC 모드가 갈리며,
     * 이 값을 validator에 넘겨 모드 교차검증(창작 의심 차단)에 사용합니다.
     */
    @Transactional
    public void generateAndSaveActivities(
    		Long pinId,
    		Long placeId,
    		String tourContentId,
    		String tourContentTypeId, 
    		String planTitle,
    		String pacePreference) {
 
        ensureDetailCached(placeId, tourContentId, tourContentTypeId);
 
        String rawIntroJson = placeDetailRepository.findRawIntroByPlaceId(placeId);
        List<ProgramInsert> programs = placeDetailRepository.findProgramsByPlaceId(placeId);
        boolean hadPrograms = !programs.isEmpty();
 
        String userPrompt = 
        		PinActivityPromptBuilder
        		.build(rawIntroJson, programs, planTitle, pacePreference)
                + "\n[pinId]\n" + pinId;
 
        String raw = llmClient.generate(PinActivityPrompts.DETAIL_PLANNER_SYSTEM, userPrompt);
 
        GeneratedPinActivities validated = pinActivityValidator.validate(raw, pinId, hadPrograms);
        pinActivityRepository.saveSuggested(validated);
 
        log.info("극소 계획 생성 완료: pinId={}, mode={}, 활동 수={}",
                pinId, validated.mode(), validated.activities().size());
    }
 
    private void ensureDetailCached(Long placeId, String tourContentId, String tourContentTypeId) {
        if (tourContentId == null) {
            log.warn("tour_content_id 없는 place(Kakao 출처 추정), 상세정보 동기화 생략: placeId={}", placeId);
            return;
        }
        if (!placeDetailRepository.existsByPlaceId(placeId)) {
            log.info("place_details 캐시 없음, TourAPI 최초 동기화: placeId={}, tourContentId={}", placeId, tourContentId);
            placeDetailSyncService.syncDetail(placeId, tourContentId, tourContentTypeId);
        }
    }
}