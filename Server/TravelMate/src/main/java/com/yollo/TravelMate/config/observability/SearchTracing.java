package com.yollo.TravelMate.config.observability;

import java.util.function.Supplier;

import org.springframework.http.client.ClientHttpRequestInterceptor;
import org.springframework.stereotype.Component;

import io.opentelemetry.api.trace.Span;
import io.opentelemetry.api.trace.SpanKind;
import io.opentelemetry.api.trace.StatusCode;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.context.Context;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import lombok.RequiredArgsConstructor;

@Component
@RequiredArgsConstructor
public class SearchTracing {

    private final Tracer tracer;

    public <T> T trace(String operation, Supplier<T> action) {
        Span span = tracer.spanBuilder(operation).startSpan();
        try (var scope = span.makeCurrent()) {
            return action.get();
        } catch (RuntimeException | Error exception) {
            span.recordException(exception);
            span.setStatus(StatusCode.ERROR);
            throw exception;
        } finally {
            span.end();
        }
    }

    public Span startServerSpan(String operation, Context parent) {
        return tracer.spanBuilder(operation)
                .setParent(parent)
                .setSpanKind(SpanKind.SERVER)
                .startSpan();
    }

    public ClientHttpRequestInterceptor tracePropagationInterceptor() {
        return (request, body, execution) -> {
            W3CTraceContextPropagator.getInstance().inject(
                    Context.current(),
                    request.getHeaders(),
                    (headers, key, value) -> headers.set(key, value)
            );
            return execution.execute(request, body);
        };
    }

    public void setRequestAttributes(Span span, String method, String route) {
        span.setAttribute("http.request.method", method);
        span.setAttribute("http.route", route);
        span.setAttribute("langsmith.span.kind", "CHAIN");
    }

    public void setHttpStatus(Span span, int status) {
        span.setAttribute("http.response.status_code", status);
        if (status >= 500) {
            span.setStatus(StatusCode.ERROR);
        }
    }
}
