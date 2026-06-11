# Performance Review — Release Candidate

## Frontend Bundle (Before vs After Lazy Loading)

| Metric | Before (Eager) | After (Lazy) | Improvement |
|--------|---------------|--------------|-------------|
| Main JS bundle | 323 kB | 229 kB | **-29%** |
| Total chunks | 1 | 37 | Code-split by route |
| CSS | 45 kB | 45 kB | Unchanged |
| Build time | — | 2.72s | 144 modules |

### Chunk Breakdown
| Page | Size (gzip) | Loaded |
|------|------------|--------|
| LoginPage | 3.04 kB (1.21 kB) | On demand |
| DashboardPage | 10.94 kB (2.83 kB) | On demand |
| CopilotPage | 14.12 kB (4.31 kB) | On demand |
| ResearchPage | 6.85 kB (2.32 kB) | On demand |
| Smallest (NotFoundPage) | 0.99 kB (0.53 kB) | On demand |

## Backend Performance

| Metric | Value | Notes |
|--------|-------|-------|
| Workers | 2 (configurable) | Uvicorn async workers |
| Worker max requests | 10,000 | Prevents memory leak accumulation |
| Keep-alive | 5s | Reduces connection overhead |
| Rate limit | 300 req/min per IP | Configurable |
| Nginx connections | 4096 | Worker connections |
| API timeout | 30s (LLM: 30s) | Configurable per-provider |

## Optimization Summary
1. Lazy loading reduces initial JS payload by 29%
2. Code splitting ensures pages load only when navigated to
3. Nginx gzip (level 6) compresses all API + static responses
4. Static assets cached 1 year with immutable directive
5. Uvicorn async workers handle concurrent I/O efficiently
