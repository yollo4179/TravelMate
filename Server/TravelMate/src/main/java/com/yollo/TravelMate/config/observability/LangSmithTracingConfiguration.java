package com.yollo.TravelMate.config.observability;

import java.time.Duration;

import org.springframework.beans.factory.annotation.Value;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;

import io.opentelemetry.api.OpenTelemetry;
import io.opentelemetry.api.trace.Tracer;
import io.opentelemetry.api.trace.propagation.W3CTraceContextPropagator;
import io.opentelemetry.context.propagation.ContextPropagators;
import io.opentelemetry.exporter.otlp.http.trace.OtlpHttpSpanExporter;
import io.opentelemetry.sdk.OpenTelemetrySdk;
import io.opentelemetry.sdk.resources.Resource;
import io.opentelemetry.sdk.trace.SdkTracerProvider;
import io.opentelemetry.sdk.trace.export.BatchSpanProcessor;

@Configuration
public class LangSmithTracingConfiguration {

    @Bean(destroyMethod = "close")
    SdkTracerProvider sdkTracerProvider(
            @Value("${LANGSMITH_API_KEY:${LANGCHAIN_API_KEY:}}") String apiKey,
            @Value("${LANGSMITH_ENDPOINT:https://api.smith.langchain.com}") String endpoint,
            @Value("${LANGSMITH_PROJECT:travelmate-search-observability}") String project
    ) {
        var builder = SdkTracerProvider.builder()
                .setResource(Resource.getDefault().toBuilder().put("service.name", "travelmate-server").build());
        if (!apiKey.isBlank()) {
            String tracesEndpoint = endpoint.replaceAll("/$", "") + "/otel/v1/traces";
            OtlpHttpSpanExporter exporter = OtlpHttpSpanExporter.builder()
                    .setEndpoint(tracesEndpoint)
                    .addHeader("x-api-key", apiKey)
                    .addHeader("Langsmith-Project", project)
                    .setTimeout(Duration.ofSeconds(10))
                    .build();
            builder.addSpanProcessor(BatchSpanProcessor.builder(exporter).build());
        }
        return builder.build();
    }

    @Bean
    OpenTelemetry openTelemetry(SdkTracerProvider tracerProvider) {
        return OpenTelemetrySdk.builder()
                .setTracerProvider(tracerProvider)
                .setPropagators(ContextPropagators.create(W3CTraceContextPropagator.getInstance()))
                .build();
    }

    @Bean
    Tracer searchTracer(OpenTelemetry openTelemetry) {
        return openTelemetry.getTracer("travelmate.search", "1.0.0");
    }

}
