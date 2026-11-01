package com.yollo.TravelMate.config.observability;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.util.UUID;
import com.fasterxml.jackson.databind.ObjectMapper;
import com.yollo.TravelMate.ai.llm.budget.LlmCallGuard;
import com.yollo.TravelMate.ai.llm.observation.*;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.util.ContentCachingRequestWrapper;
import org.springframework.web.util.ContentCachingResponseWrapper;

@Component
@Order(org.springframework.core.Ordered.HIGHEST_PRECEDENCE + 20)
public class ExecutionObservationFilter extends OncePerRequestFilter {
    private final ExecutionRecorder recorder;
    private final ObjectMapper mapper;
    private final ObservationContext.Mode mode;

    public ExecutionObservationFilter(
            ExecutionRecorder recorder,
            ObjectMapper mapper,
            @Value("${travelmate.observation.mode:LIVE}") ObservationContext.Mode mode
    ) {
        this.recorder = recorder;
        this.mapper = mapper;
        this.mode = mode;
    }

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !path.equals("/api/v1/conversation/turns")
                && !path.startsWith("/api/v1/plans") && !path.startsWith("/api/v1/planning-jobs/");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain chain
    ) throws ServletException, IOException {
        var cachedRequest = new ContentCachingRequestWrapper(request, Integer.MAX_VALUE);
        var cachedResponse = new ContentCachingResponseWrapper(response);
        String requestId = UUID.randomUUID().toString();
        String turnId = label(request.getHeader("Idempotency-Key"), UUID.randomUUID().toString());
        String conversationId = label(request.getHeader("X-Conversation-Id"), UUID.randomUUID().toString());
        var context = ObservationContext.Context.builder().requestId(requestId).turnId(turnId)
                .conversationId(conversationId).caseId(label(request.getHeader("X-Evaluation-Case-Id"), null))
                .inputSha256(label(request.getHeader("X-Evaluation-Input-Sha256"), null))
                .mode(mode).phase(ObservationContext.Phase.REQUEST).sink(recorder::write).build();
        long started = System.nanoTime();
        response.setHeader("X-Request-Id", requestId);
        response.setHeader("X-Conversation-Id", conversationId);
        try (var scope = ObservationContext.open(context)) {
            try {
                chain.doFilter(cachedRequest, cachedResponse);
            } finally {
                String rawBody = new String(cachedRequest.getContentAsByteArray(), StandardCharsets.UTF_8);
                var input = mapper.createObjectNode().put("method", request.getMethod()).put("path", request.getRequestURI())
                        .put("rawBody", rawBody).put("bodySha256", LlmCallGuard.sha256(rawBody));
                var output = mapper.createObjectNode().put("httpStatus", cachedResponse.getStatus())
                        .put("durationMs", (System.nanoTime() - started) / 1_000_000.0);
                String body = new String(cachedResponse.getContentAsByteArray(), StandardCharsets.UTF_8);
                try { output.set("response", mapper.readTree(body)); }
                catch (com.fasterxml.jackson.core.JsonProcessingException exception) { output.put("unparsedBody", body); }
                try {
                    ObservationContext.record(ObservationContext.Event.API_REQUEST, input);
                    ObservationContext.record(ObservationContext.Event.API_RESPONSE, output);
                } finally {
                    cachedResponse.copyBodyToResponse();
                }
            }
        }
    }

    private static String label(String value, String fallback) {
        if (value == null || value.isBlank() || value.length() > 128) return fallback;
        return value;
    }
}
