# RegIntel AI — Complete Metrics Inventory

Every metric defined in the codebase, organized by module.

---

## 1. Retrieval Metrics (`app/evaluation/metrics.py`)

Standard Information Retrieval metrics computed from retrieved chunk IDs vs. ground-truth relevant IDs.

### `compute_recall_at_k(retrieved_ids, relevant_ids, k)`
- **Formula:** `|relevant ∩ top-K| / |relevant|`
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 if no relevant IDs provided

### `compute_precision_at_k(retrieved_ids, relevant_ids, k)`
- **Formula:** `|relevant ∩ top-K| / K`
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 if k=0

### `compute_mrr(retrieved_ids, relevant_ids)`
- **Formula:** `1 / rank_of_first_relevant`
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 if no relevant item found

### `compute_hit_rate(retrieved_ids, relevant_ids, k=10)`
- **Formula:** `1 if any relevant in top-K else 0`
- **Range:** `{0.0, 1.0}`

### `compute_ndcg_at_k(retrieved_ids, relevant_ids, k, relevance_scores=None)`
- **Formula:** `DCG@K / IDCG@K`
- **DCG:** `Σ (2^rel_i - 1) / log2(i + 1)` for i=1..K
- **Range:** `[0.0, 1.0]`
- **Supports:** binary or graded relevance scores

### `compute_all_metrics(retrieved_results, relevant_ids, k_values=None)`
- **Returns:** dict of all above metrics at each K value

### `aggregate_metrics(query_results)`
- **Returns:** mean of each metric across all queries

### `composite_score(query_results, weights=None)`
- **Formula:** weighted sum of precision, recall, MRR, NDCG
- **Default weights:** 0.25 each (configurable)

---

## 2. Answer Evaluation Metrics (`app/services/evaluation/__init__.py`)

Metrics computed from a `FinalAnswerResponse` object (answer text, citations, faithfulness score, attributions).

### `faithfulness(response)`
- **Source:** reads `response.faithfulness_score` (from hallucination detector)
- **Range:** `[0.0, 1.0]`
- **Note:** delegates to the HallucinationGuardService

### `answer_relevance(response, query)`
- **Formula:** `token_overlap(query, answer_text)`
- **Answer text:** concatenation of `executive_summary` + `detailed_explanation`
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 for empty answer

### `citation_accuracy(response)`
- **Formula:** `cited_claims / total_claims`
- **Source:** `response.citations.executive_summary` + `response.citations.detailed_explanation`
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 if no claims extracted

### `source_attribution_accuracy(response)`
- **Formula:** `0.5 × coverage_ratio + 0.5 × validity_ratio`
- **Coverage ratio:** `response.attribution_coverage_ratio`
- **Validity ratio:** attributions with valid `chunk_id + document_id` / total attributions
- **Range:** `[0.0, 1.0]`

### `completeness(response, chunks)`
- **Formula:** `max(token_overlap(answer_text, chunk.content))` across all chunks
- **Range:** `[0.0, 1.0]`
- **Returns:** 0.0 if no chunks or empty answer

### `groundedness(response)`
- **Formula:** `0.6 × citation_accuracy + 0.4 × faithfulness`
- **Range:** `[0.0, 1.0]`

### `hallucination_rate(response)`
- **Formula:** `1.0 - hallucination_detected` (1.0 if no hallucination, 0.0 if detected)
- **Range:** `{0.0, 1.0}`

### `evidence_coverage(response)`
- **Source:** `response.attribution_coverage_ratio`
- **Range:** `[0.0, 1.0]`

### `compute_all(response, query, chunks, metrics=None)`
- **Returns:** list of `MetricScore` objects for all 8 metrics above

---

## 3. Confidence Scoring Factors (`app/services/confidence/factors.py`)

Each factor returns `{"score": float, "details": {...}}`. All scores in `[0.0, 1.0]`.

| Factor | Weight | Function | Input | Method |
|--------|--------|----------|-------|--------|
| `retrieval_relevance_factor` | 0.25 | `factors.py:48` | retrieval_scores or chunk_scores | Mean of scores |
| `reranker_confidence_factor` | 0.20 | `factors.py:80` | reranker_scores or None | Mean of scores; 0.0 if None |
| `source_agreement_factor` | 0.15 | `factors.py:103` | chunks with `source` field | Maps primary_share [0.5,1.0] → [0.0,1.0] |
| `chunk_coverage_factor` | 0.20 | `factors.py:146` | chunks with scores | `count_score × (0.5 + 0.5 × mean_score)` |
| `citation_coverage_factor` | 0.20 | `factors.py:184` | coverage ratio or answer dict | Prefer precomputed, else `supporting / fields_filled` |

### Aggregation (`ConfidenceCalculator.aggregate()` in `calculator.py:73`)
- **Formula:** weighted sum of available factor scores
- **Redistribution:** unavailable factor weights redistributed proportionally
- **Level mapping:** `≥0.9 → HIGH`, `≥0.7 → MEDIUM`, `<0.7 → LOW`

### Confidence Flags
Generated automatically when certain conditions detected:
- `LOW_CITATION_COVERAGE`
- `NO_RERANK_SCORES`
- `SINGLE_SOURCE`
- `LOW_CHUNK_COUNT`
- `HIGH_SCORE_VARIANCE`
- `EMPTY_CHUNKS`
- `NO_ANSWER`

---

## 4. Retrieval Benchmark Suite (`app/services/embedding/benchmark_suite.py`)

### Per-Query Metrics (`QueryEvaluationResult`)
| Metric | Formula |
|--------|---------|
| `precision_at_5` | matches in top-5 / 5 |
| `precision_at_10` | matches in top-10 / 10 |
| `recall_at_5` | matches in top-5 / expected_count |
| `recall_at_10` | matches in top-10 / expected_count |
| `mrr` | 1 / rank of first match |
| `hit_at_5` | 1 if any match in top-5 |
| `hit_at_10` | 1 if any match in top-10 |

### Aggregate Metrics (`BenchmarkSummaryMetrics`)
| Metric | Formula |
|--------|---------|
| `mean_precision_at_5` | mean of per-query precision@5 |
| `mean_precision_at_10` | mean of per-query precision@10 |
| `mean_recall_at_5` | mean of per-query recall@5 |
| `mean_recall_at_10` | mean of per-query recall@10 |
| `mrr` | mean of per-query MRR |
| `hit_rate_at_5` | fraction of queries with hit@5 |
| `hit_rate_at_10` | fraction of queries with hit@10 |

---

## 5. Reranker Benchmark (`app/services/reranker/service.py`)

### Per-Query Metrics (`BenchmarkResult`)
| Metric | Description |
|--------|-------------|
| `num_candidates` | Number of input candidates for query |
| `latency_ms` | Total rerank latency |
| `scoring_latency_ms` | Cross-encoder scoring latency |
| `top_score` | Highest reranker score |
| `candidates_returned` | Number after filtering |

### Aggregate Metrics (`BenchmarkReport`)
| Metric | Formula |
|--------|---------|
| `total_queries` | Count |
| `total_candidates` | Sum across queries |
| `avg_latency_ms` | Mean of per-query latencies |
| `p50_latency_ms` | 50th percentile |
| `p95_latency_ms` | 95th percentile |
| `p99_latency_ms` | 99th percentile |
| `avg_scoring_latency_ms` | Mean of per-query scoring latencies |
| `throughput_qps` | `queries / total_elapsed_seconds` |
| `avg_candidates_per_query` | `total_candidates / total_queries` |
| `avg_top_score` | Mean of per-query top scores |

---

## 6. Hallucination Benchmark (`benchmarks/benchmark_hallucination.py`)

### Per-Case Metrics
| Field | Description |
|-------|-------------|
| `faithfulness_score` | Float [0,1] from guard |
| `hallucination_detected` | Boolean |
| `risk_level` | Enum: `LOW` / `MEDIUM` / `HIGH` |
| `total_claims` | Count of claims extracted |
| `supported_count` | Claims supported by source |
| `unsupported_count` | Claims not supported |
| `unsupported_claims` | List of `{claim_id, claim, reason}` |
| `latency_ms` | Verification time |
| `expectations_met` | List of satisfied expectations |
| `all_expectations_met` | Boolean |

### Aggregate Metrics
| Metric | Formula |
|--------|---------|
| `detection_accuracy` | `cases_meeting_expectations / total_cases` |
| `average_faithfulness_score` | Mean faithfulness across cases |
| `hallucination_rate` | `hallucinated_cases / total_cases` |
| `average_latency_ms` | Mean latency |
| `p95_latency_ms` | 95th percentile latency |

---

## 7. Observability Metrics (`app/services/observability/__init__.py`)

### `APIMetrics` — Retrieval API Counters
| Counter | Type |
|---------|------|
| `total_requests` | int |
| `successful_requests` | int |
| `failed_requests` | int |
| `total_latency_ms` | float |
| `average_latency_ms` | float (derived: total / count) |
| `error_rate` | float (derived: failed / total) |
| `strategy_counts` | `Dict[str, int]` (per strategy) |
| `reranker_used` | int |
| `reranker_skipped` | int |
| `endpoint_counts` | `Dict[str, int]` (per endpoint) |
| `error_counts` | `Dict[str, int]` (per error type) |
| `uptime_seconds` | float |

### `AgentMetrics` — Agent Framework Counters
| Counter | Type |
|---------|------|
| `agents_registered` | int |
| `invocations_total` | int |
| `invocations_succeeded` | int |
| `invocations_failed` | int |
| `invocations_timed_out` | int |
| `retries_total` | int |
| `coordination_runs` | int |
| `coordination_succeeded` | int |
| `coordination_failed` | int |
| `coordination_steps_total` | int |
| `total_duration_ms` | float |
| `average_duration_ms` | float (derived) |
| `by_agent` | `Dict[str, int]` |
| `by_capability` | `Dict[str, int]` |
| `by_status` | `Dict[str, int]` |
| `last_invocation_at` | Optional timestamp |

### `IntelligenceAgentMetrics` — Per-Agent Counters
| Counter | Type | Scope |
|---------|------|-------|
| `total_invocations` | int | All agents |
| `total_successful` | int | All agents |
| `total_failed` | int | All agents |
| `total_collaborations` | int | Cross-agent |
| `research_invocations` | int | Research only |
| `research_successful` | int | Research only |
| `research_failed` | int | Research only |
| `research_total_duration_ms` | float | Research only |
| `research_confidence_total` | float | Research only |
| `compliance_invocations` | int | Compliance only |
| `compliance_successful` | int | Compliance only |
| `compliance_failed` | int | Compliance only |
| `compliance_total_duration_ms` | float | Compliance only |
| `compliance_confidence_total` | float | Compliance only |
| `risk_invocations` | int | Risk only |
| `risk_successful` | int | Risk only |
| `risk_failed` | int | Risk only |
| `risk_total_duration_ms` | float | Risk only |
| `risk_confidence_total` | float | Risk only |
| `recommendations_generated` | int | |
| `recommendations_accepted` | int | |
| `recommendations_rejected` | int | |
| `evidence_items_shared` | int | |
| `by_mode` | `Dict[str, int]` | Research mode breakdown |
| `by_scenario_kind` | `Dict[str, int]` | Risk scenario breakdown |
| `by_collaboration_pair` | `Dict[str, int]` | Agent→agent handoffs |

### `RequestContext` — Per-Request Telemetry
| Field | Type |
|-------|------|
| `request_id` | str (UUID) |
| `endpoint` | str |
| `strategy` | str |
| `latency_ms` | float (derived) |
| `error` | Optional[str] |
| `rerank_used` | bool |

---

## 8. Confidence Metrics (`app/services/confidence/metrics.py`)

### `ConfidenceMetrics` — In-Process Collector
| Counter | Type |
|---------|------|
| `total_requests` | int |
| `high_count` | int (level = HIGH) |
| `medium_count` | int (level = MEDIUM) |
| `low_count` | int (level = LOW) |
| `confidence_sum` | float |
| `confidence_min` | float |
| `confidence_max` | float |
| `average_score` | float (derived: sum / count) |
| `average_score` per level | float |
| `score_distribution` | `p50, p95, min, max, stdev` |
| `factor_stats` | per-factor: `{count, mean, min, max, stdev}` |
| `flag_counts` | per-flag: `Dict[str, int]` |

---

## 9. `token_overlap` — Shared Utility (`app/services/citation/mapper.py`)

Not a standalone metric but used as the foundation for several evaluation metrics.

- **Formula:** `0.6 × cosine(content_keywords) + 0.4 × jaccard(content_keywords)`
- **Content keywords:** tokens filtered to content-bearing words (length > 2, lowercase, not stopwords)
- **Range:** `[0.0, 1.0]`
- **Used by:** `answer_relevance`, `completeness`, `LexicalFaithfulnessChecker`

---

## Summary Table

| Domain | Source File | Metric Count |
|--------|-----------|:-----------:|
| Retrieval (IR) | `app/evaluation/metrics.py` | 5 base + 2 aggregate |
| Answer Evaluation | `app/services/evaluation/__init__.py` | 8 |
| Confidence Factors | `app/services/confidence/factors.py` | 5 |
| Retrieval Benchmark | `app/services/embedding/benchmark_suite.py` | 7 per-query + 7 aggregate |
| Reranker Benchmark | `app/services/reranker/service.py` | 4 per-query + 10 aggregate |
| Hallucination Benchmark | `benchmarks/benchmark_hallucination.py` | 9 per-case + 5 aggregate |
| Observability: APIMetrics | `app/services/observability/__init__.py` | 12 |
| Observability: AgentMetrics | `app/services/observability/__init__.py` | 16 |
| Observability: IntelAgentMetrics | `app/services/observability/__init__.py` | 22 |
| Confidence Metrics | `app/services/confidence/metrics.py` | 9 |
| Shared utility | `app/services/citation/mapper.py` | 1 |
| **Total** | | **~110 unique metric fields** |

All metrics are custom in-process implementations. No external evaluation frameworks (Ragas, DeepEval, etc.) are used.
