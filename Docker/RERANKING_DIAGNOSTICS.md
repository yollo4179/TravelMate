# Reranker diagnostics

Reranking execution is selected through strategy classes under `embedding-server/app/reranking/strategies/`:

- `cross_encoder_predict` calls `CrossEncoder.predict(pairs, batch_size=configured_batch_size)`.
- `instrumented_predict` calls that same API and adds CUDA synchronization around it to measure its completed wall time.
- `autocast_fp16` calls that same API under CUDA float16 autocast as an optimization candidate; use it only if ranking evaluation passes.
- `manual_diagnostic` runs the equivalent preprocessing, batching, transfer, forward, and output steps separately to expose stage timings.

`RERANK_DIAGNOSTICS_ENABLED=true` selects `manual_diagnostic`; otherwise the default is `cross_encoder_predict`. These paths must not be treated as the same implementation until the fixed-input benchmark confirms token-input and output parity.

Set `RERANK_EXECUTION_STRATEGY=autocast_fp16` to run the experimental CUDA FP16 path. The model parameters remain FP32; autocast uses lower precision for supported GPU operations. Keep the original strategy unless the same judged evaluation set retains its ranking metrics.

To enable detailed profiling for a local diagnostic run, add these values to the repository root `.env`:

```dotenv
RERANK_DIAGNOSTICS_ENABLED=true
RERANK_BATCH_SIZE=32
```

Restart the stack after changing the setting:

```bash
bash Docker/stack-up.sh --build
bash Docker/stack-wait.sh
```

The batch size defaults to 32, matching the installed Sentence Transformers default. All strategies now use `RERANK_BATCH_SIZE`, including the three `predict` strategies. The archived 2026-10-25 benchmark used the library default of 32 in the predict paths; those paths did not forward a nondefault batch setting at that time. Changing the batch size keeps the retrieval candidate count separate: 30 candidates with batch size 8 are evaluated in four batches. Keep it fixed while measuring the current 30-candidate flow. Change it only in a later optimization experiment.

The 2026-10-26 regression check captured actual preprocessing batches with `RERANK_BATCH_SIZE=8`: original predict, FP16 autocast, and manual diagnostics all processed `[8, 8, 8, 6]` over the same 30 candidates. The query/body fingerprint matched the archived batch-32 run, and its full baseline ranking was unchanged. Predict and manual scores matched exactly; FP16 preserved the full ranking with a maximum score delta of 0.000396. This is one fixed-query check, not a rerun of the 60-case quality evaluation. See `embedding-server/reports/reranker-batch8-verification-20261026.json`.

The subsequent judged comparison on 2026-10-26 froze candidate IDs and complete bodies for all 60 fully supported V1.4 search queries and compared FP32/FP16 batches 8/16/32. All settings retained the 15 ranking metrics per query and identical unpadded token IDs. FP16 batch 8 was selected: reranking-only mean 547 ms and p95 717 ms; a length-stratified 12-query, three-repeat confirmation also passed. Full rank order matched FP32 batch 32 for 41/60 queries; metric equality does not establish quality equality for unjudged candidates. The subsequent 80-query live API run recorded mean 1.607 s and p95 2.015 s, with all 60 eligible-case quality means unchanged. These are RTX 4050 Laptop GPU measurements, not general performance guarantees.

The validated local profile is:

```dotenv
RERANK_EXECUTION_STRATEGY=autocast_fp16
RERANK_BATCH_SIZE=8
RERANK_DIAGNOSTICS_ENABLED=false
```

The deployed container and all 80 live reranking spans confirmed that profile on CUDA. The versioned dataset was not changed; local artifacts are under `Evaluation/runs/search/v1.4.0/batch-fp16-20261026/` and the corresponding live collection directory.

## Fixed-input strategy comparison

For a judged batch comparison across the V1.4 search cases, `Evaluation/tracks/search/batch_experiment.py` runs inside the GPU embedding image with `Evaluation` mounted at `/evaluation`. It freezes the live top-30 candidates once per fully supported query, then evaluates the registered `cross_encoder_predict` and `autocast_fp16` strategies at batch sizes 8, 16, and 32 without changing candidate count or token limits. It records scores, ranks, unpadded token hashes, batch shapes, and reranking-only wall time. The quality gate rejects any setting with a per-query ranking metric decrease relative to FP32 batch 32. A length-stratified subset is repeated for confirmation. Its results belong in `Evaluation/runs/`, outside the frozen dataset. API/Kafka end-to-end timing must still be measured after deploying a selected configuration.

The benchmark uses the current embedding and pgvector retrieval once, freezes the resulting ordered candidate texts, warms each strategy, and repeats each strategy with that same input. It reports uninstrumented `predict`, synchronized `predict`, CUDA FP16 autocast, and manual diagnostic timings separately. It captures the actual preprocessing tensors outside the timed runs to verify token IDs, truncation, padding, and batch parity. Score deltas, rank equality, and top-10 overlap show whether a faster path preserves the ranking.

Run it without the API container using the same GPU Compose overlay and retained model/database volumes:

```bash
source Docker/stack-common.sh
compose+=( -f "$compose_repo_dir/Docker/docker-compose.stack.gpu.yml" )
"${compose[@]}" stop embedding
"${compose[@]}" run --rm --no-deps --entrypoint python embedding \
  -m app.reranking.benchmark --query "서울 카페" --warmups 2 --runs 5
"${compose[@]}" up -d embedding
```

Relevance metrics require human judgments for the exact query and candidate set. When rank order is identical, deterministic NDCG/MAP/MRR/Precision/Recall/F1 values are identical for any fixed judgments; rank parity is not itself a relevance judgment.

### RTX 4050 fixed-input result (2026-10-25)

For `서울 카페`, the benchmark held 30 candidate descriptions and their order fixed, warmed each path twice, and measured five runs. All paths used batch size 32. Original `predict` had a 1,902 ms median; the manual diagnostic path took 1,924 ms. CUDA FP16 autocast took 618 ms (3.08× faster), kept the exact full rank order and top-10, and changed scores by at most 0.000282. Token IDs and attention masks matched the original path exactly: padded length 338, maximum actual length 338, zero pairs truncated, configured sequence limit 8,192. Model parameters were FP32 on the RTX 4050 Laptop GPU.

This query has no human relevance judgments, so its absolute NDCG/MAP/MRR/Precision/Recall/F1 values were not computed. The identical ranking guarantees those metrics would be unchanged for any fixed judgments on this exact candidate set. Validate on the project's judged queries before making FP16 the default. The full machine-readable result is in `embedding-server/reports/reranker-comparison-20261025.json`.

## LangSmith spans

Search traces retain the request query and filters. The FastAPI worker spans appear beneath the Spring `recommendation.kafka_roundtrip` span:

```text
travelmate.search
`-- recommendation.kafka_roundtrip
    |-- recommendation.worker_queue
    `-- recommendation.pipeline
        |-- embedding.model_inference
        |-- database.pgvector_search
        `-- reranking.model_inference
            |-- reranking.tokenize
            |-- reranking.gpu_transfer
            |-- reranking.model_forward
            `-- reranking.output
```

The Kafka round trip is the parent wait interval. Its duration already contains queueing, model work, result publishing, and response delivery; do not add it to the child spans.

Reranker attributes include model and load time, actual parameter dtype, selected device, candidate count, explicit batch size/count, query, candidate character lengths, actual token counts from the attention mask, padded lengths, padding ratio, and inference index since model load. Character-length sorting proxies are labeled as character lengths rather than token counts. A SHA-256 fingerprint of the query plus ordered candidate texts lets LangSmith distinguish a repeated identical input without storing those texts. `first_inference_after_model_load` distinguishes the first real call from later calls; `first_inference_for_input` distinguishes an identical-input repeat. Startup warm-up is explicitly recorded as not configured, so a later call is not automatically called "warmed".

Detailed spans split tokenization, device transfer, model forward, and output conversion. `model_forward.cuda_event_ms` measures CUDA work between recorded events. `model_forward.call_wall_ms`, `pre_sync_wait_ms`, and `completion_wait_ms` distinguish the host model call from waits around CUDA work. Transfer call, pre-sync wait, and completion wait are recorded separately too. These wall and CUDA event values use different clocks; do not add them together. Explicit synchronization count and wait time are also recorded.

CUDA synchronization affects diagnostic request latency. Compare the parent `reranking.model_inference` duration in `execution_mode=diagnostic` with a matching standard-mode run before drawing conclusions about production latency. The `memory_*` measurements are process-wide allocator values; peak values are cumulative process peaks and are not request-scoped. `concurrent_overlap=true` means another rerank call overlapped this measurement, so memory and CUDA timing may include shared work.

The manual diagnostic strategy uses the same model preprocessing defaults, candidate texts, candidate order, and configured batch size as `CrossEncoder.predict()`. It does not set a different maximum sequence length. Still, compare captured input tensors and score vectors before treating it as equivalent. Use the fixed-input benchmark before selecting one optimization at a time, then compare relevance metrics on the same judged candidate set.
