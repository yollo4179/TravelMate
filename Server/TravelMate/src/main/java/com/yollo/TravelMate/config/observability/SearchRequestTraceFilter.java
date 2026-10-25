package com.yollo.TravelMate.config.observability;

import java.io.IOException;
import java.util.Collections;

import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.Context;
import io.opentelemetry.context.propagation.TextMapGetter;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import lombok.RequiredArgsConstructor;

@Component
@Order(Ordered.HIGHEST_PRECEDENCE + 10)
@RequiredArgsConstructor
public class SearchRequestTraceFilter extends OncePerRequestFilter {

    private static final TextMapGetter<HttpServletRequest> REQUEST_HEADER_GETTER = new TextMapGetter<>() {
        @Override
        public Iterable<String> keys(HttpServletRequest request) {
            return Collections.list(request.getHeaderNames());
        }

        @Override
        public String get(HttpServletRequest request, String key) {
            return request.getHeader(key);
        }
    };

    private final SearchTracing searchTracing;

    @Override
    protected boolean shouldNotFilter(HttpServletRequest request) {
        String path = request.getRequestURI();
        return !path.equals("/api/places/search") && !path.equals("/api/v1/places/search");
    }

    @Override
    protected void doFilterInternal(
            HttpServletRequest request,
            HttpServletResponse response,
            FilterChain filterChain
    ) throws ServletException, IOException {
        long startedAtNanos = System.nanoTime();
        Context extractedParent = W3CTraceContextPropagator.getInstance()
                .extract(Context.current(), request, REQUEST_HEADER_GETTER);
        String route = request.getMethod() + " " + request.getRequestURI();
        Span span = searchTracing.startServerSpan("travelmate.search", extractedParent);
        searchTracing.setRequestAttributes(span, request.getMethod(), request.getRequestURI());
        span.setAttribute("search.ranking_mode", request.getParameter("rankingMode") == null
                ? "RERANKED"
                : request.getParameter("rankingMode"));
        span.setAttribute("search.limit", request.getParameter("limit") == null
                ? "10"
                : request.getParameter("limit"));
        span.setAttribute("http.route", route);
        setRequestAttribute(span, "search.query", request.getParameter("query"));
        setRequestAttribute(span, "search.region", request.getParameter("region"));
        setRequestAttribute(span, "search.city", request.getParameter("city"));
        setRequestAttribute(span, "search.category", request.getParameter("category"));

        try (var scope = span.makeCurrent()) {
            filterChain.doFilter(request, response);
            searchTracing.setHttpStatus(span, response.getStatus());
        } catch (IOException | ServletException | RuntimeException exception) {
            span.recordException(exception);
            span.setStatus(io.opentelemetry.api.trace.StatusCode.ERROR);
            throw exception;
        } finally {
            span.setAttribute("search.total_elapsed_ms", (System.nanoTime() - startedAtNanos) / 1_000_000.0);
            span.end();
        }
    }

    private static void setRequestAttribute(Span span, String key, String value) {
        if (value != null && !value.isBlank()) {
            span.setAttribute(key, value);
        }
    }
}
