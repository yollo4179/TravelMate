"""OpenTelemetry tracing configured for LangSmith OTLP ingestion."""

from __future__ import annotations

import os

from opentelemetry import trace
from opentelemetry.trace import Tracer
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


def configure_tracing() -> TracerProvider | None:
    api_key = os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY")
    if not api_key:
        return None

    endpoint = os.getenv("LANGSMITH_ENDPOINT", "https://api.smith.langchain.com").rstrip("/")
    project = os.getenv("LANGSMITH_PROJECT", "travelmate-search-observability")
    exporter = OTLPSpanExporter(
        endpoint=f"{endpoint}/otel/v1/traces",
        headers={"x-api-key": api_key, "Langsmith-Project": project},
        timeout=10,
    )
    provider = TracerProvider(
        resource=Resource.create({"service.name": "travelmate-embedding"})
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
    return provider


def tracer() -> Tracer:
    return trace.get_tracer("travelmate.embedding", "1.0.0")
