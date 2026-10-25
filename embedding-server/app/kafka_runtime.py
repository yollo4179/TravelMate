import asyncio
import json
import logging
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer
from anyio import to_thread
from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

from app.embedder import embedder
from app.observability import tracer
from app.reranker import reranker

LOGGER = logging.getLogger(__name__)
RETRIEVE_TOP_K = 30


class PlaceEventType(StrEnum):
    UPSERTED = "PLACE_UPSERTED"
    DELETED = "PLACE_DELETED"


class RankingMode(StrEnum):
    RERANKED = "RERANKED"
    SEMANTIC_ONLY = "SEMANTIC_ONLY"


class KafkaRuntime:
    def __init__(self, database_pool: Any) -> None:
        self.database_pool = database_pool
        self.bootstrap_servers = os.environ["KAFKA_BOOTSTRAP_SERVERS"]
        self.place_changes_topic = os.environ.get(
            "KAFKA_PLACE_CHANGES_TOPIC",
            "travelmate.place-changes.v1",
        )
        self.request_topic = os.environ.get(
            "KAFKA_RECOMMENDATION_REQUESTS_TOPIC",
            "travelmate.recommendation-requests.v1",
        )
        self.result_topic = os.environ.get(
            "KAFKA_RECOMMENDATION_RESULTS_TOPIC",
            "travelmate.recommendation-results.v1",
        )
        self.producer = AIOKafkaProducer(
            bootstrap_servers=self.bootstrap_servers,
            enable_idempotence=True,
            value_serializer=lambda value: json.dumps(
                value,
                ensure_ascii=False,
                allow_nan=False,
                separators=(",", ":"),
            ).encode("utf-8"),
        )
        self.place_consumer = AIOKafkaConsumer(
            self.place_changes_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id="travelmate-place-indexer-v1",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            max_poll_interval_ms=600_000,
        )
        self.request_consumer = AIOKafkaConsumer(
            self.request_topic,
            bootstrap_servers=self.bootstrap_servers,
            group_id="travelmate-recommendation-worker-v1",
            enable_auto_commit=False,
            auto_offset_reset="earliest",
            value_deserializer=lambda value: json.loads(value.decode("utf-8")),
            max_poll_interval_ms=600_000,
        )
        self.tasks: list[asyncio.Task[None]] = []

    async def start(self) -> None:
        await self.producer.start()
        await self.place_consumer.start()
        await self.request_consumer.start()
        self.tasks = [
            asyncio.create_task(self._consume_place_changes(), name="place-change-consumer"),
            asyncio.create_task(self._consume_recommendation_requests(), name="recommendation-consumer"),
            asyncio.create_task(self._process_place_jobs(), name="place-index-worker"),
            asyncio.create_task(self._process_recommendation_jobs(), name="recommendation-worker"),
            asyncio.create_task(self._publish_result_outbox(), name="recommendation-result-relay"),
        ]

    async def stop(self) -> None:
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.request_consumer.stop()
        await self.place_consumer.stop()
        await self.producer.stop()

    async def _consume_place_changes(self) -> None:
        async for message in self.place_consumer:
            try:
                await self._accept_place_event(message.value)
                await self.place_consumer.commit()
            except Exception:
                LOGGER.exception("Failed to persist place change event")
                await asyncio.sleep(1)

    async def _accept_place_event(self, event: dict[str, Any]) -> None:
        event_id = uuid.UUID(event["event_id"])
        place_id = int(event["place_id"])
        source_version = int(event["source_version"])
        event_type = PlaceEventType(event["event_type"])
        source = event.get("source") or {}
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False)

        async with self.database_pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    INSERT INTO place_index_jobs
                        (job_id, event_id, place_id, source_version, payload)
                    VALUES ($1, $2, $3, $4, $5::jsonb)
                    ON CONFLICT (event_id) DO NOTHING
                    """,
                    uuid.uuid4(),
                    event_id,
                    place_id,
                    source_version,
                    payload,
                )
                if event_type == PlaceEventType.DELETED:
                    await connection.execute(
                        """
                        INSERT INTO place_embeddings
                            (place_id, source_version, latest_seen_version, name, embedding, document_status)
                        VALUES ($1, $2, $2, '[deleted]', NULL, 'DELETED')
                        ON CONFLICT (place_id) DO UPDATE SET
                            latest_seen_version = EXCLUDED.latest_seen_version,
                            source_version = EXCLUDED.source_version,
                            name = '[deleted]', description = NULL, embedding = NULL,
                            document_status = 'DELETED', indexed_at = now()
                        WHERE place_embeddings.latest_seen_version <= EXCLUDED.latest_seen_version
                        """,
                        place_id,
                        source_version,
                    )
                else:
                    await connection.execute(
                        """
                        INSERT INTO place_embeddings
                            (place_id, source_version, latest_seen_version, name, description,
                             region, city, category, source_category, latitude, longitude,
                             tour_content_id, image_url, homepage_url, embedding, document_status)
                        VALUES ($1, $2, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, NULL, 'READY')
                        ON CONFLICT (place_id) DO UPDATE SET
                            latest_seen_version = GREATEST(place_embeddings.latest_seen_version, EXCLUDED.latest_seen_version)
                        """,
                        place_id,
                        source_version,
                        source["name"],
                        source.get("description"),
                        source.get("region"),
                        source.get("city"),
                        source.get("category"),
                        source.get("source_category"),
                        source.get("latitude"),
                        source.get("longitude"),
                        source.get("tour_content_id"),
                        source.get("image_url"),
                        source.get("homepage_url"),
                    )

    async def _consume_recommendation_requests(self) -> None:
        async for message in self.request_consumer:
            try:
                await self._accept_recommendation_request(message.value)
                await self.request_consumer.commit()
            except Exception:
                LOGGER.exception("Failed to persist recommendation request")
                await asyncio.sleep(1)

    async def _accept_recommendation_request(self, event: dict[str, Any]) -> None:
        if event.get("schema_version") != 1 or event.get("event_type") != "RECOMMENDATION_REQUESTED":
            raise ValueError("Unsupported recommendation event")
        if not isinstance(event.get("query"), str) or not event["query"].strip():
            raise ValueError("Recommendation query must not be empty")
        if not 1 <= int(event.get("limit", 0)) <= 20:
            raise ValueError("Recommendation limit is outside the supported range")
        request_id = uuid.UUID(event["request_id"])
        event_id = uuid.UUID(event["event_id"])
        context_version = int(event["context_version"])
        payload = json.dumps(event, ensure_ascii=False, allow_nan=False)
        async with self.database_pool.acquire() as connection:
            await connection.execute(
                """
                INSERT INTO recommendation_requests
                    (request_id, event_id, context_version, payload)
                VALUES ($1, $2, $3, $4::jsonb)
                ON CONFLICT (request_id) DO NOTHING
                """,
                request_id,
                event_id,
                context_version,
                payload,
            )

    async def _process_place_jobs(self) -> None:
        while True:
            job = await self._claim_job("place_index_jobs")
            if job is None:
                await asyncio.sleep(0.5)
                continue
            try:
                await self._index_place_job(job)
            except Exception:
                LOGGER.exception("Place indexing job failed: %s", job["job_id"])
                await self._finish_place_job(job["job_id"], "FAILED", "INDEXING_FAILED")

    async def _index_place_job(self, job: Any) -> None:
        payload = json.loads(job["payload"])
        event_type = PlaceEventType(payload["event_type"])
        source = payload.get("source") or {}
        if event_type == PlaceEventType.DELETED:
            await self._finish_place_job(job["job_id"], "SUCCEEDED", None)
            return

        current_version = await self.database_pool.fetchval(
            "SELECT latest_seen_version FROM place_embeddings WHERE place_id = $1",
            job["place_id"],
        )
        if current_version != job["source_version"]:
            await self._finish_place_job(job["job_id"], "SUPERSEDED", None)
            return

        embedding_text = f"{source['name']}. {source.get('description') or ''}".strip()
        with tracer().start_as_current_span("embedding.model_inference") as span:
            span.set_attribute("embedding.device", embedder.device)
            span.set_attribute("embedding.text_count", 1)
            vector = (await to_thread.run_sync(lambda: embedder.embed([embedding_text])))[0]
        vector_text = "[" + ",".join(map(str, vector)) + "]"
        async with self.database_pool.acquire() as connection:
            async with connection.transaction():
                updated = await connection.execute(
                    """
                    UPDATE place_embeddings
                    SET source_version = $2, name = $3, description = $4, region = $5,
                        city = $6, category = $7, source_category = $8, latitude = $9,
                        longitude = $10, tour_content_id = $11, image_url = $12,
                        homepage_url = $13, embedding = $14::vector,
                        document_status = 'READY', indexed_at = now()
                    WHERE place_id = $1 AND latest_seen_version = $2
                    """,
                    job["place_id"],
                    job["source_version"],
                    source["name"],
                    source.get("description"),
                    source.get("region"),
                    source.get("city"),
                    source.get("category"),
                    source.get("source_category"),
                    source.get("latitude"),
                    source.get("longitude"),
                    source.get("tour_content_id"),
                    source.get("image_url"),
                    source.get("homepage_url"),
                    vector_text,
                )
                status = "SUCCEEDED" if updated == "UPDATE 1" else "SUPERSEDED"
                await connection.execute(
                    "UPDATE place_index_jobs SET status = $2, updated_at = now() WHERE job_id = $1",
                    job["job_id"],
                    status,
                )

    async def _process_recommendation_jobs(self) -> None:
        while True:
            request = await self._claim_job("recommendation_requests")
            if request is None:
                await asyncio.sleep(0.25)
                continue
            try:
                await self._complete_recommendation(request)
            except Exception:
                LOGGER.exception("Recommendation job failed: %s", request["request_id"])
                await self._save_recommendation_result(request, self._failed_result(request))

    async def _complete_recommendation(self, request: Any) -> None:
        payload = json.loads(request["payload"])
        if not 1 <= int(payload["limit"]) <= 20:
            raise ValueError("Recommendation limit is outside the supported range")
        trace_headers = {
            header_name: payload[header_name]
            for header_name in ("traceparent", "tracestate")
            if payload.get(header_name)
        }
        parent_context = TraceContextTextMapPropagator().extract(trace_headers)
        pipeline_started_at = time.perf_counter()
        query = payload["query"]
        ranking_mode = RankingMode(payload["ranking_mode"])
        request_created_at = request["created_at"]
        requested_at = datetime.fromisoformat(payload["requested_at"].replace("Z", "+00:00"))
        queue_elapsed_ms = max(0.0, (datetime.now(UTC) - request_created_at).total_seconds() * 1000)
        kafka_to_database_ms = max(0.0, (request_created_at - requested_at).total_seconds() * 1000)

        with tracer().start_as_current_span(
            "recommendation.worker_queue",
            context=parent_context,
            start_time=int(request_created_at.timestamp() * 1_000_000_000),
        ) as queue_span:
            queue_span.set_attribute("search.query", query)
            queue_span.set_attribute("search.ranking_mode", ranking_mode.value)
            queue_span.set_attribute("recommendation.worker_queue.elapsed_ms", queue_elapsed_ms)
            queue_span.set_attribute("recommendation.kafka_to_database_ms", kafka_to_database_ms)

        with tracer().start_as_current_span(
            "recommendation.pipeline",
            context=parent_context,
        ) as pipeline_span:
            pipeline_span.set_attribute("search.query", query)
            pipeline_span.set_attribute("search.ranking_mode", ranking_mode.value)
            pipeline_span.set_attribute("search.limit", int(payload["limit"]))
            pipeline_span.set_attribute("search.top_k", RETRIEVE_TOP_K)
            pipeline_span.set_attribute("search.filters", json.dumps(payload.get("filters", {}), ensure_ascii=False))

            embedding_started_at = time.perf_counter()
            with tracer().start_as_current_span("embedding.model_inference") as embedding_span:
                embedding_span.set_attribute("embedding.device", embedder.device)
                embedding_span.set_attribute("embedding.text_count", 1)
                embedding_span.set_attribute("embedding.query", query)
                query_embedding = (await to_thread.run_sync(lambda: embedder.embed([query])))[0]
                embedding_span.set_attribute("embedding.dimension", embedder.getDimension())
                embedding_span.set_attribute(
                    "embedding.elapsed_ms",
                    (time.perf_counter() - embedding_started_at) * 1000,
                )

            vector = "[" + ",".join(map(str, query_embedding)) + "]"
            candidates = await self._retrieve_candidates(payload, vector)
            pipeline_span.set_attribute("search.candidate_count", len(candidates))

            if candidates and ranking_mode == RankingMode.RERANKED:
                texts = [candidate["description"] or candidate["name"] for candidate in candidates]
                reranking_started_at = time.perf_counter()
                with tracer().start_as_current_span("reranking.model_inference") as reranking_span:
                    reranking_span.set_attribute("reranking.device", reranker.device)
                    reranking_span.set_attribute("reranking.model", reranker.model_name)
                    reranking_span.set_attribute("reranking.query", query)
                    reranking_span.set_attribute("reranking.candidate_count", len(texts))
                    worker_dispatch_at = time.perf_counter()

                    def run_reranker() -> list[float]:
                        execution_wait_ms = (time.perf_counter() - worker_dispatch_at) * 1000
                        return reranker.rerank(query, texts, execution_wait_ms)

                    scores = await to_thread.run_sync(run_reranker)
                    reranking_span.set_attribute("reranking.score_count", len(scores))
                    reranking_span.set_attribute("reranking.elapsed_ms", (time.perf_counter() - reranking_started_at) * 1000)
                    reranking_span.set_attribute("reranking.batch_size", reranker.batch_size)
                    reranking_span.set_attribute("reranking.batch_count", reranker.batch_count(len(texts)))
                    reranking_span.set_attribute("reranking.execution_mode", reranker.execution_mode)
                    if scores:
                        reranking_span.set_attribute("reranking.score_min", min(scores))
                        reranking_span.set_attribute("reranking.score_max", max(scores))
                ranked = sorted(zip(candidates, scores, strict=True), key=lambda item: item[1], reverse=True)
                items = [self._to_result_item(row, rank, score) for rank, (row, score) in enumerate(ranked[: payload["limit"]], 1)]
                rerank_status = "APPLIED"
            else:
                items = [
                    self._to_result_item(row, rank, None)
                    for rank, row in enumerate(candidates[: payload["limit"]], 1)
                ]
                rerank_status = "SKIPPED" if candidates else "EMPTY"

            pipeline_span.set_attribute("search.returned_count", len(items))
            pipeline_span.set_attribute("reranking.status", rerank_status)
            pipeline_span.set_attribute(
                "search.total_elapsed_ms",
                (time.perf_counter() - pipeline_started_at) * 1000,
            )
            result = {
                "schema_version": 1,
                "event_id": str(uuid.uuid4()),
                "event_type": "RECOMMENDATION_COMPLETED",
                "request_id": str(request["request_id"]),
                "context_version": request["context_version"],
                "status": "COMPLETED",
                "query": query,
                "completed_at": datetime.now(UTC).isoformat(),
                "ranking_mode_requested": ranking_mode.value,
                "ranking_mode_applied": ranking_mode.value,
                "rerank_status": rerank_status,
                "fallback_reason": None,
                "applied_filters": payload.get("filters", {}),
                "candidate_count": len(candidates),
                "returned_count": len(items),
                "items": items,
                "warnings": [],
            }
            output_preview = [
                {
                    "rank": item["rank"],
                    "place_id": item["place_id"],
                    "name": item["name"],
                    "semantic_score": item["semantic_score"],
                    "rerank_score": item["rerank_score"],
                }
                for item in items
            ]
            pipeline_span.set_attribute("search.results_preview", json.dumps(output_preview, ensure_ascii=False))
            await self._save_recommendation_result(request, result)

    async def _retrieve_candidates(self, payload: dict[str, Any], vector: str) -> list[dict[str, Any]]:
        filters = payload.get("filters", {})
        conditions = [
            "document_status = 'READY'",
            "embedding IS NOT NULL",
            "1 - (embedding <=> $1::vector) >= 0",
        ]
        parameters: list[Any] = [vector]
        for column, value in (
            ("region", filters.get("region")),
            ("city", filters.get("city")),
            ("category", filters.get("category")),
        ):
            if value and value.strip():
                parameters.append(value)
                conditions.append(f"{column} = ${len(parameters)}")

        excluded_ids = filters.get("exclude_place_ids", [])
        if excluded_ids:
            parameters.append(excluded_ids)
            conditions.append(f"NOT (place_id = ANY(${len(parameters)}::bigint[]))")

        area = filters.get("area")
        if area:
            center = area["center"]
            parameters.extend([center["lat"], center["lat"], center["lon"], area["radius_meters"]])
            latitude_a, latitude_b, longitude, radius = range(len(parameters) - 3, len(parameters) + 1)
            conditions.append(
                f"""latitude IS NOT NULL AND longitude IS NOT NULL
                AND latitude BETWEEN -90 AND 90 AND longitude BETWEEN -180 AND 180
                AND 6371000 * 2 * asin(sqrt(least(1.0,
                    power(sin(radians(latitude - ${latitude_a}) / 2), 2)
                    + cos(radians(${latitude_b})) * cos(radians(latitude))
                    * power(sin(radians(longitude - ${longitude}) / 2), 2)))) <= ${radius}"""
            )

        parameters.extend([vector, RETRIEVE_TOP_K])
        vector_parameter, limit_parameter = len(parameters) - 1, len(parameters)
        query = f"""
            SELECT place_id, source_version, latest_seen_version, name, description,
                   region, city, category, source_category, latitude, longitude,
                   tour_content_id, image_url, homepage_url,
                   1 - (embedding <=> $1::vector) AS semantic_score
            FROM place_embeddings
            WHERE {' AND '.join(conditions)}
            ORDER BY embedding <=> ${vector_parameter}::vector
            LIMIT ${limit_parameter}
        """
        retrieval_started_at = time.perf_counter()
        with tracer().start_as_current_span("database.pgvector_search") as retrieval_span:
            retrieval_span.set_attribute("db.system", "postgresql")
            retrieval_span.set_attribute("db.operation.name", "SELECT")
            retrieval_span.set_attribute("db.collection.name", "place_embeddings")
            retrieval_span.set_attribute("search.top_k", RETRIEVE_TOP_K)
            async with self.database_pool.acquire() as connection:
                rows = await connection.fetch(query, *parameters)
            retrieval_span.set_attribute("search.candidate_count", len(rows))
            retrieval_span.set_attribute(
                "search.retrieval_elapsed_ms",
                (time.perf_counter() - retrieval_started_at) * 1000,
            )
        return [dict(row) for row in rows]

    @staticmethod
    def _to_result_item(candidate: dict[str, Any], rank: int, rerank_score: float | None) -> dict[str, Any]:
        return {
            "place_id": candidate["place_id"],
            "rank": rank,
            "name": candidate["name"],
            "description": candidate["description"],
            "region": candidate["region"],
            "city": candidate["city"],
            "category": candidate["category"],
            "source_category": candidate["source_category"],
            "latitude": candidate["latitude"],
            "longitude": candidate["longitude"],
            "tour_content_id": candidate["tour_content_id"],
            "image_url": candidate["image_url"],
            "homepage_url": candidate["homepage_url"],
            "semantic_score": candidate["semantic_score"],
            "rerank_score": rerank_score,
            "source_version": candidate["source_version"],
            "latest_seen_version": candidate["latest_seen_version"],
            "index_config_version": "bge-m3-v1",
        }

    async def _save_recommendation_result(self, request: Any, result: dict[str, Any]) -> None:
        result_event_id = uuid.UUID(result["event_id"])
        serialized_result = json.dumps(result, ensure_ascii=False, allow_nan=False)
        async with self.database_pool.acquire() as connection:
            async with connection.transaction():
                await connection.execute(
                    """
                    UPDATE recommendation_requests
                    SET status = $2, result_payload = $3::jsonb, updated_at = now()
                    WHERE request_id = $1 AND status = 'RUNNING'
                    """,
                    request["request_id"],
                    result["status"],
                    serialized_result,
                )
                await connection.execute(
                    """
                    INSERT INTO recommendation_result_outbox (event_id, request_id, payload)
                    VALUES ($1, $2, $3::jsonb)
                    ON CONFLICT (request_id) DO NOTHING
                    """,
                    result_event_id,
                    request["request_id"],
                    serialized_result,
                )

    def _failed_result(self, request: Any) -> dict[str, Any]:
        payload = json.loads(request["payload"])
        return {
            "schema_version": 1,
            "event_id": str(uuid.uuid4()),
            "event_type": "RECOMMENDATION_FAILED",
            "request_id": str(request["request_id"]),
            "context_version": request["context_version"],
            "status": "FAILED",
            "error_code": "RECOMMENDATION_FAILED",
            "failed_stage": "PROCESSING",
            "retryable": True,
            "query": payload["query"],
            "completed_at": datetime.now(UTC).isoformat(),
            "items": [],
        }

    async def _publish_result_outbox(self) -> None:
        while True:
            async with self.database_pool.acquire() as connection:
                events = await connection.fetch(
                    """
                    SELECT event_id, request_id, payload::text AS payload
                    FROM recommendation_result_outbox
                    WHERE published_at IS NULL
                    ORDER BY created_at
                    LIMIT 50
                    """
                )
            for event in events:
                payload = json.loads(event["payload"])
                try:
                    await self.producer.send_and_wait(
                        self.result_topic,
                        payload,
                        key=str(event["request_id"]).encode("utf-8"),
                    )
                    await self.database_pool.execute(
                        "UPDATE recommendation_result_outbox SET published_at = now() WHERE event_id = $1",
                        event["event_id"],
                    )
                except Exception:
                    LOGGER.exception("Recommendation result publish failed: %s", event["event_id"])
                    break
            await asyncio.sleep(0.5)

    async def _claim_job(self, table: str) -> Any | None:
        if table not in {"place_index_jobs", "recommendation_requests"}:
            raise ValueError("Unsupported job table")
        key_column = "job_id" if table == "place_index_jobs" else "request_id"
        async with self.database_pool.acquire() as connection:
            async with connection.transaction():
                return await connection.fetchrow(
                    f"""
                    WITH next_job AS (
                        SELECT {key_column} FROM {table}
                        WHERE status = 'PENDING'
                        ORDER BY created_at
                        FOR UPDATE SKIP LOCKED
                        LIMIT 1
                    )
                    UPDATE {table} AS job
                    SET status = 'RUNNING', attempt_count = attempt_count + 1, updated_at = now()
                    FROM next_job
                    WHERE job.{key_column} = next_job.{key_column}
                    RETURNING job.*
                    """
                )

    async def _finish_place_job(self, job_id: uuid.UUID, status: str, error_code: str | None) -> None:
        await self.database_pool.execute(
            """
            UPDATE place_index_jobs SET status = $2, last_error_code = $3, updated_at = now()
            WHERE job_id = $1
            """,
            job_id,
            status,
            error_code,
        )
