package com.yollo.TravelMate.domain.conversation.pipeline;

import java.util.Arrays;
import java.util.EnumMap;
import java.util.Map;
import com.fasterxml.jackson.core.type.TypeReference;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.domain.conversation.data.DialogueCut;
import com.yollo.TravelMate.domain.plan.data.response.PlanningResponse.JobStatus;
import org.springframework.core.io.DefaultResourceLoader;

/**
 * LiLi's lines that need no model call: known job statuses, and the fallback when her own line could not be used.
 * Failures with varying reasons are not here; they go back to LiLi's follow-up.
 */
public final class LiliFixedLines {
    public static final String RESOURCE = "classpath:conversation/persona/lili-fixed-lines-v1.json";

    public enum Line {
        JOB_QUEUED,
        JOB_RUNNING,
        JOB_SUCCEEDED,
        EXPLANATION_UNAVAILABLE,
        REPLY_UNAVAILABLE,
        PLAN_UNAVAILABLE,
        // A template: the server fills in the area the user asked for and what the place data holds.
        OUTSIDE_COVERAGE
    }

    private static final Map<JobStatus, Line> STATUS_LINES = Map.of(
            JobStatus.QUEUED, Line.JOB_QUEUED,
            JobStatus.RUNNING, Line.JOB_RUNNING,
            JobStatus.SUCCEEDED, Line.JOB_SUCCEEDED
    );

    private LiliFixedLines() {}

    public static DialogueCut line(Line line) {
        return Holder.LINES.get(line);
    }

    public static DialogueCut outsideCoverage(
            String requestedRegion,
            String coveredRegions,
            String coveredCategories
    ) {
        var template = line(Line.OUTSIDE_COVERAGE);
        String text = template.text().replace("{requested}", requestedRegion)
                .replace("{regions}", coveredRegions).replace("{categories}", coveredCategories);
        return new DialogueCut(text, template.emotion());
    }

    public static DialogueCut line(JobStatus status) {
        var line = STATUS_LINES.get(status);
        if (line == null) throw new IllegalArgumentException("No fixed LiLi line for job status " + status);
        return line(line);
    }

    // Loaded once on first use; a missing line fails before the first lookup reaches a user.
    private static final class Holder {
        private static final Map<Line, DialogueCut> LINES = load();

        private static Map<Line, DialogueCut> load() {
            String json = PromptTemplates.load(new DefaultResourceLoader(), RESOURCE);
            try {
                Map<Line, DialogueCut> lines = new ObjectMapper().readValue(json, new TypeReference<EnumMap<Line, DialogueCut>>() {});
                if (!lines.keySet().containsAll(Arrays.asList(Line.values()))) {
                    throw new IllegalStateException("Every fixed LiLi line needs text and an emotion: " + RESOURCE);
                }
                return Map.copyOf(lines);
            } catch (java.io.IOException exception) {
                throw new IllegalStateException("LiLi fixed lines unavailable: " + RESOURCE, exception);
            }
        }
    }
}
