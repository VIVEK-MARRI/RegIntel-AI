# TODO - Module 4.7 Retrieval Analytics Platform (Bridge + Data-Quality Auditing)

## Step 1: Repo understanding (read + map integration points)
- [ ] Inspect `app/repositories/analytics.py` for existing query/upsert patterns
- [ ] Inspect alembic migration `alembic/versions/001_create_analytics_tables.py` for constraints/uniques
- [ ] Inspect analytics reporting/report generator code (if separate) to see where to add audit sections

## Step 2: Define “evaluation ingest” contract (schemas)
- [ ] Add Pydantic schemas in `app/schemas/analytics.py` for:
  - ingest benchmark reports
  - ingest evaluation metrics batch
  - ingest reranker gain
  - ingest historical evaluation runs (lightweight)
- [ ] Add Pydantic schemas for audit summary + audit fields

## Step 3: Implement ingest + audit computation (service/repo)
- [ ] Add `AnalyticsService` methods:
  - `ingest_evaluation_run(...)`
  - `compute_quality_audit_summary(...)`
- [ ] Add repository methods for idempotent writes/upserts (or store audit in `metadata_json` if schema migration avoided)

## Step 4: Expose ingest + quality endpoints (API)
- [ ] Add endpoints in `app/api/v1/analytics.py`:
  - `POST /ingest/evaluation/run`
  - `GET /quality/audit`
- [ ] Ensure `/reports` includes:
  - `data_quality_summary` section with:
    - relevance_match_rate
    - missing_relevance_ids
    - unmatched_chunk_ids
    - empty_judgment_queries
    - retrieval_without_ground_truth

## Step 5: Wire evaluation outputs -> analytics ingest
- [ ] Inspect `app/evaluation/reporting.py` / artifacts format used by Module 4.6
- [ ] Add ingestion adapter in analytics ingest that parses those artifacts into metrics + audit metadata

## Step 6: Tests + validation
- [ ] Add/extend tests under `tests/test_analytics/` for:
  - ingest writes
  - audit summary aggregation
  - report inclusion
- [ ] Run `python -m pytest -q tests/test_analytics`

## Step 7: Docs
- [ ] Update README or module docs with:
  - ingest payload example
  - audit interpretation guidance
