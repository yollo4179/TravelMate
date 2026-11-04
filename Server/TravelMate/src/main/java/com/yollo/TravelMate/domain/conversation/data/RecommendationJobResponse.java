package com.yollo.TravelMate.domain.conversation.data;

import java.util.UUID;
import com.fasterxml.jackson.databind.JsonNode;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;

/** result is the finished ConversationResponse (cards, citations and LiLi's cuts); null until the job ends. */
public record RecommendationJobResponse(
        UUID jobId,
        JobStatus status,
        String statusUrl,
        JsonNode result,
        String errorMessage
) {
    public static final String STATUS_PATH = "/api/v1/recommendation-jobs/";

    public static String statusUrl(UUID jobId) {
        return STATUS_PATH + jobId;
    }
}
