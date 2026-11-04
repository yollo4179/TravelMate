package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.EnumMap;
import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import org.springframework.core.io.DefaultResourceLoader;

/**
 * LiLi's fixed lines for a planning job that has not failed. A known status needs no second model call;
 * only failures, whose reason varies, go back to LiLi's follow-up.
 */
public final class LiliStatusLines {
    public static final String RESOURCE = "classpath:conversation/persona/lili-job-status-v1.json";

    private LiliStatusLines() {}

    public static DialogueCut line(JobStatus status) {
        var cut = Holder.LINES.get(status);
        if (cut == null) throw new IllegalArgumentException("No fixed LiLi line for job status " + status);
        return cut;
    }

    // Loaded once on first use; a status without a line fails before the first lookup reaches a user.
    private static final class Holder {
        private static final Map<JobStatus, DialogueCut> LINES = load();

        private static Map<JobStatus, DialogueCut> load() {
            String json = PromptTemplates.load(new DefaultResourceLoader(), RESOURCE);
            try {
                Map<JobStatus, DialogueCut> lines = new ObjectMapper().readValue(json, new TypeReference<EnumMap<JobStatus, DialogueCut>>() {});
                var required = JobStatus.pendingValues().stream().toList();
                if (!lines.keySet().containsAll(required) || !lines.containsKey(JobStatus.SUCCEEDED) || lines.containsKey(JobStatus.FAILED)) {
                    throw new IllegalStateException("LiLi status lines must cover pending and completed jobs and leave failures to LiLi");
                }
                return Map.copyOf(lines);
            } catch (java.io.IOException exception) {
                throw new IllegalStateException("LiLi status lines unavailable: " + RESOURCE, exception);
            }
        }
    }
}
