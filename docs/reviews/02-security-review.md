# Security Review — Release Candidate

## Authentication
| Feature | Status | Details |
|---------|--------|---------|
| Password hashing | ✅ | PBKDF2-SHA256, 600K iterations, random salt |
| JWT signing | ✅ | HS256, min 32-char secret, expiration, issuer/audience validation |
| Token refresh | ✅ | Rotation with revocation of old refresh token |
| Account lockout | ✅ | Configurable max attempts + duration, 429 response |
| Login rate limiting | ✅ | Nginx 30r/s + backend sliding window 300/min |

## Authorization
| Feature | Status | Details |
|---------|--------|---------|
| Role-based access | ✅ | Admin, analyst, auditor, viewer roles |
| Route protection | ✅ | ProtectedRoute + RequireRole guards on frontend |
| API key auth | ✅ | Optional, configurable, per-key quotas |

## Network Security
| Feature | Status | Details |
|---------|--------|---------|
| CSP header | ✅ | `default-src 'self'` |
| HSTS | ✅ | `max-age=31536000; includeSubDomains` |
| X-Frame-Options | ✅ | `DENY` |
| X-Content-Type-Options | ✅ | `nosniff` |
| CORS | ✅ | Strict-by-default, configurable origins |
| Rate limiting | ✅ | Nginx + backend sliding window |
| Docker security | ✅ | Non-root user, no-new-privileges, cap_drop all |

## Audit & Monitoring
| Feature | Status | Details |
|---------|--------|---------|
| Request audit | ✅ | Every request logged (method, path, status, duration, client) |
| Threat detection | ✅ | SQL injection, suspicious UA, rapid-fire detection |
| Health monitoring | ✅ | Liveness, readiness, deep diagnostic endpoints |
| Request tracing | ✅ | X-Request-ID propagation |

## Gap Analysis
| Gap | Impact | Mitigation |
|-----|--------|------------|
| No DB encryption at rest | Low | Handled by managed PostgreSQL |
| No secrets vault integration | Medium | Optional; env vars supported |
| No mTLS between services | Low | Single-host deployment via nginx |
