package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.Arrays;
import java.util.List;
import java.util.Map;
import java.util.function.Supplier;
import java.util.stream.Collectors;
import java.util.stream.StreamSupport;
import com.yollo.TravelMate.domain.conversation.data.CharacterEmotion;
import com.yollo.TravelMate.domain.conversation.data.ConversationAnswerKind;
import com.yollo.TravelMate.domain.conversation.data.ConversationIntent;
import com.yollo.TravelMate.domain.conversation.data.LiliBranch;
import com.yollo.TravelMate.domain.conversation.service.ConversationAnswerContract;
import com.yollo.TravelMate.domain.conversation.service.ConversationEvidencePreparation;
import com.yollo.TravelMate.domain.conversation.service.RecommendationExecutionFacts.ExclusionStatus;
import com.yollo.TravelMate.domain.conversation.tool.ConversationTool;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;

/**
 * Prompt tokens filled from the enums and contracts the server enforces.
 * The prompt names the same closed value sets as the Strict schema, so an enum change cannot leave a stale list behind.
 */
public enum PromptVocabulary {
        // [요청 봉투]
        INTENT_HINTS("intentHints", () -> names(Arrays.asList(ConversationIntent.values()))),      // UI 버튼 값 전체
        AUTO_INTENT("autoIntent", ConversationIntent.AUTO::name),                                   // 버튼 미선택 값

        // [서버 사전 검색]
        EVIDENCE_FAILED("evidenceFailed", ConversationEvidencePreparation.State.FAILED::name),      // 빈 결과와 구분할 검색 실패 상태
        EXCLUSION_VERIFIED("exclusionVerified", ExclusionStatus.VERIFIED::name),                    // 필터와 반환 목록에서 확인한 제외 완료
        EXCLUSION_UNVERIFIED("exclusionUnverified", ExclusionStatus.UNVERIFIED::name),              // 제외 요청을 완료로 말할 수 없는 상태

        // [등록 도구]
        SEARCH_PLACES("searchPlaces", ConversationTool.Name.SEARCH_PLACES::wireName),
        GENERATE_PLAN("generatePlan", ConversationTool.Name.GENERATE_PLAN::wireName),
        GET_PLANNING_JOB("getPlanningJob", ConversationTool.Name.GET_PLANNING_JOB::wireName),
        PENDING_JOB_STATUSES("pendingJobStatuses", () -> names(JobStatus.pendingValues())),       // 완성 계획이 아닌 작업 상태

        // [최종 응답]
        ANSWER_FIELDS("answerFields", PromptVocabulary::answerFields),                             // Strict JSON 필수 필드
        ANSWER_KINDS("answerKinds", () -> names(Arrays.asList(ConversationAnswerKind.values()))),
        FINAL_INTENTS("finalIntents", () -> names(ConversationIntent.finalValues())),
        EMOTIONS("emotions", () -> names(Arrays.asList(CharacterEmotion.values()))),                // LiLi catalog.json 태그와 같은 집합

        // [LiLi]
        PERSONA("persona", LiliPersona::text),                                                      // 라우터·추천·계획이 함께 쓰는 단일 페르소나
        BRANCH_CHAT("branchChat", LiliBranch.CHAT::name),
        BRANCH_CLARIFY("branchClarify", LiliBranch.CLARIFY::name),
        BRANCH_SEARCH("branchSearch", LiliBranch.SEARCH_PLACES::name),
        BRANCH_PLAN("branchPlan", LiliBranch.GENERATE_PLAN::name),
        BRANCH_JOB("branchJob", LiliBranch.GET_PLANNING_JOB::name);

        private static final String SEPARATOR = "/";
        private final String token;
        private final Supplier<String> value;

        PromptVocabulary(String token, Supplier<String> value) {
            this.token = token;
            this.value = value;
        }

        public static Map<String, String> tokens() {
            return Arrays.stream(values()).collect(Collectors.toUnmodifiableMap(entry -> entry.token, entry -> entry.value.get()));
        }

        private static String names(List<? extends Enum<?>> values) {
            return values.stream().map(Enum::name).collect(Collectors.joining(SEPARATOR));
        }

        // The schema's required array is sorted; its property map order is not stable across JVM starts.
        private static String answerFields() {
            return StreamSupport.stream(ConversationAnswerContract.schema().path("required").spliterator(), false)
                    .map(field -> field.asText())
                    .collect(Collectors.joining(SEPARATOR));
        }
}
