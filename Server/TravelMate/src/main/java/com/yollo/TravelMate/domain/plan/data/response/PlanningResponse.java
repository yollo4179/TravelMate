package com.yollo.TravelMate.domain.plan.data.response;

import java.util.List;
import java.util.UUID;
import com.yollo.TravelMate.domain.plan.data.request.PlanContext;

public final class PlanningResponse {
    private PlanningResponse() {}
    public enum JobStatus {
        QUEUED(true),
        RUNNING(true),
        SUCCEEDED(false),
        FAILED(false);

        private final boolean pending;

        JobStatus(boolean pending) {
            this.pending = pending;
        }

        /** Accepted or running jobs are not completed plans; the conversation prompt names exactly these. */
        public static List<JobStatus> pendingValues() {
            return java.util.Arrays.stream(values()).filter(status -> status.pending).toList();
        }
    }
    public record Job(
            UUID jobId,
            JobStatus status,
            String statusUrl,
            Long planId,
            String errorMessage
    ) {}
    public record Draft(
            Long planId,
            PlanContext context,
            String title,
            List<Pin> pins,
            List<String> warnings,
            String description
    ) {
        public Draft(Long planId, PlanContext context, String title, List<Pin> pins, List<String> warnings) {
            this(planId, context, title, pins, warnings, null);
        }
    }
    public record Pin(
            Long placeId,
            String name,
            double latitude,
            double longitude,
            int stayMinutes,
            int sequence,
            String explanation
    ) {
        public Pin(Long placeId, String name, double latitude, double longitude, int stayMinutes, int sequence) {
            this(placeId, name, latitude, longitude, stayMinutes, sequence, null);
        }
    }
}
