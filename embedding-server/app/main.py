from contextlib import asynccontextmanager
from collections.abc import AsyncIterator, Awaitable, Callable
import os

import asyncpg
from fastapi import FastAPI, Request, Response
from opentelemetry.trace import SpanKind, StatusCode
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.observability import configure_tracing, tracer
from app.kafka_runtime import KafkaRuntime
from app.enrichment.repository import ensure_schema as ensure_enrichment_schema
from routers import embed, rerank


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    tracer_provider = configure_tracing()
    database_url = os.environ.get("DATABASE_URL")
    application.state.database_pool = (
        await asyncpg.create_pool(
            dsn=database_url,
            min_size=1,
            max_size=int(os.environ.get("DATABASE_POOL_MAX_SIZE", "10")),
            command_timeout=10,
        )
        if database_url
        else None
    )
    application.state.kafka_runtime = None
    if application.state.database_pool is not None:
        await ensure_enrichment_schema(application.state.database_pool)
    if application.state.database_pool is not None and os.environ.get("KAFKA_BOOTSTRAP_SERVERS"):
        kafka_runtime = KafkaRuntime(application.state.database_pool)
        await kafka_runtime.start()
        application.state.kafka_runtime = kafka_runtime
    yield
    if application.state.kafka_runtime is not None:
        await application.state.kafka_runtime.stop()
    if application.state.database_pool is not None:
        await application.state.database_pool.close()
    if tracer_provider is not None:
        tracer_provider.force_flush()
        tracer_provider.shutdown()


app = FastAPI(title="Embedding Server", lifespan=lifespan)
app.include_router(embed.router)
app.include_router(rerank.router)


@app.middleware("http")
async def trace_request(
    request: Request,
    call_next: Callable[[Request], Awaitable[Response]],
) -> Response:
    parent_context = TraceContextTextMapPropagator().extract(carrier=request.headers)
    operation = f"{request.method} {request.url.path}"
    with tracer().start_as_current_span(
        operation,
        context=parent_context,
        kind=SpanKind.SERVER,
    ) as span:
        span.set_attribute("http.request.method", request.method)
        span.set_attribute("url.path", request.url.path)
        try:
            response = await call_next(request)
        except Exception as exception:
            span.record_exception(exception)
            span.set_status(StatusCode.ERROR)
            raise
        span.set_attribute("http.response.status_code", response.status_code)
        if response.status_code >= 500:
            span.set_status(StatusCode.ERROR)
        return response
