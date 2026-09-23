# Audit Architecture - STAGE 12

## 1. Product purpose
A trust surface for traceability: what happened (records), whether the trail
verifies (hash-chain integrity), what supports each event (evidence), and what
was summarized (compliance reports). Conservative by design — uncertainty is
never rendered as health.

## 2. Audit domain model
- **Record** (`AuditRecord`): immutable, hash-chained event with actor, action,
  severity, subject, description, request context, chain fields, and free-form
  details. NO outcome field exists — none is displayed.
- **Integrity** (hand-built dict): `{intact, message, total, valid, invalid,
  chain_length, last_chain_hash}`. No `checked_at`, no `broken_chains`.
- **Evidence** (`AuditEvidence`): attached to records via `record_id`, with
  kind/title/description, structured `content`, SHA-256 `content_hash`,
  collector, timestamps, source URI, tags.
- **Report** (`ComplianceReport`): titled, kind-typed, status-lifed report with
  epoch periods, sections, record/evidence references, attestation.
- **Lineage** (`DecisionLineage` DAG): verified to exist, no UI (deferred §23).

```mermaid
flowchart TB
    Page[AuditPage\nTabs: records|evidence|reports]
    Page --> Rec[Audit Records\nGET /audit/records + filters/pagination\nGET /audit/records/:id]
    Rec --> Det[record detail\nchain fields + scalar details\n+ associated evidence]
    Page --> Int[Integrity Check\nGET /audit/integrity\nintact / compromised / unavailable]
    Page --> Ev[Evidence\nGET /audit/evidence?record_id=\nGET /audit/evidence/:id]
    Page --> Rep[Reports\nGET /audit/reports?kind=\nPOST /audit/reports]
    Rep --> RepDet[report detail\nsections + record/evidence jumps]
    Page --> RQ[React Query]
    RQ --> K1[auditKeys.records params]
    RQ --> K2[auditKeys.record id]
    RQ --> K3[auditKeys.integrity]
    RQ --> K4[auditKeys.evidence ...]
    RQ --> K5[auditKeys.reports ...]
```

## 3. Record model
`audit_id, timestamp` (epoch float), `actor/actor_role`, `action` (18-enum),
`severity` (5-enum), `subject_type/subject_id`, `description`,
`details` (free dict — scalar fields only rendered),
`ip_address/user_agent/source_module`, `prev_hash/record_hash` (SHA-256 hex),
`sequence`, `metadata` (not rendered — free-form, no safe semantics).

## 4. Integrity model
Exactly the endpoint dict. Tri-state only: data+`intact:true`, data+
`intact:false` (or missing `intact` — fail-closed), request error. No derived
percentages (the old `toIntegrityView().percent` + ProgressBar are gone).

## 5. Integrity semantics
`verify_chain` walks genesis→head checking linkage and recomputing each
record's SHA-256. The UI says "hash-chain integrity" and nothing stronger:
never "data is correct", "tamper-proof", "legally valid". Failure messages
("break at sequence=…", "tamper detected at audit_id=…") render verbatim.
The `invalid = max(total, 1)` backend quirk on compromise is displayed as
returned, without reinterpretation.

## 6. Evidence model
As §2, plus: `content` renders scalar entries only with an explicit note that
it is a structured payload, not an excerpt; `content_hash` shown verbatim with
copy; `source_uri` linked only for http(s); "Associated evidence" / "Associated
record" wording throughout (no proof claims); unlinked evidence states so.

## 7. Report model
As §2. Sections render in `order` with title/summary/string findings/
recommendations/evidence links (metrics dicts skipped — no defined display
semantics). Periods via date formatting, completed/attestation shown when
present. Generation takes title (≥3 chars), kind, regulator, period datetimes,
and comma-separated section titles; the created report is selected and the
list invalidated. NO export UI — no backend export exists.

## 8. Endpoint inventory
Verified in `app/api/v1/audit.py` (+ contract-tested list/integrity shapes).

| Method | Path | Use | Notes |
|---|---|---|---|
| GET | `/audit/stats` | Overview metrics (NEW) | Totals, chain length, severity distribution |
| POST | `/audit/records` | NOT USED | Manual entries would pollute the trail (deferred §23) |
| GET | `/audit/records` | Filtered history | action/severity/actor/subject_type/subject_id/source_module/after/before/text_query/page/page_size; chain order (oldest first) |
| GET | `/audit/records/{id}` | Detail on demand | 404 → error panel, no substitution |
| GET | `/audit/integrity` | Banner (always mounted) | Hand-built dict; see §4/§5 |
| POST | `/audit/evidence` | NOT USED | Same rationale as record creation |
| GET | `/audit/evidence` | `?record_id=` filter | Bare array |
| GET | `/audit/evidence/{id}` | Detail on demand | 404 → error panel |
| GET | `/audit/lineage/{id}` | NOT USED | DAG needs its own surface (deferred) |
| POST | `/audit/reports` | Generation (201) | Real request model (§7) |
| GET | `/audit/reports` | `?kind=` filter | Bare array, stored order |
| GET | `/audit/reports/{id}` | NOT USED | List items are full objects; no duplicate fetch |

## 9. Filters
Server-side only, all in the query key: action (18), severity (5), actor,
subject type/id, source module, after/before (datetime-local → epoch seconds),
and `text_query` (backend matches description/details/subject_id — the UI says
exactly this). Evidence tab: `record_id`. Reports: `kind`.

## 10. Pagination
Backend envelope is unwrapped by the service (Stage-02 behavior), so the UI
uses prev/next with a short-page heuristic (`page_size=50`) and "Page N · M
shown" — totals come from `/stats`, never from rows, and "Page N of M" is
never claimed.

## 11. Sorting
Backend chain order (ascending sequence, oldest first) is preserved and
labeled as such. No "recent" language, no client resorting.

## 12. Query/cache architecture
- `auditKeys.integrity()` / `stats()` — banner + metrics, always mounted.
- `records(params)` — every filter + page in the key.
- `record(id)` / `evidenceDetail(id)` — detail on demand.
- `evidence({record_id?})`, `reports({kind?})`.
No generic `["audit"]` queries; no per-row prefetch; tab panels mount on
activation.

## 13. Invalidation
Report generation → `["audit","reports"]` prefix. Nothing else mutates from
this UI, and no other domain writes audit records from the frontend — so no
cross-domain invalidation exists, by decision (documented, not omitted).

## 14. Detail behavior
Record/evidence details fetch by id on selection with loading/error/empty
states; unknown ids error without substitution. Report detail renders from
the selected list object. Cross-links (evidence↔record, report refs↔tabs)
switch tabs and select by id through real queries.

## 15. Integrity UX
Banner is the first element under the header: success ("…intact." + counts +
head hash), danger ("…FAILED." + reason + counts, `role=alert`), or warning
("…unavailable… NOT the same as intact" + retry). Failure can never be
collapsed away or mistaken for health.

## 16. Loading/error/empty states
Independent Skeletons; ErrorState+Retry with backend messages (integrity
transport failure vs compromised chain are different states and read
differently); EmptyStates distinguish no-records/no-evidence/no-reports from
failures, and empty results explicitly disclaim integrity meaning.

## 17. Responsive behavior
Single column; tables scroll in `overflow-x-auto`; hashes/IDs truncate with
full values in titles + copy buttons; detail grids collapse 4→2 columns.
Verified 390/768/1024/1440, zero page-level overflow
(`landing/_review/ds12-*`, gitignored local artifacts).

## 18. Accessibility
One h1; integrity banner uses `role=status`/`role=alert` with full-text
explanations (never color-only); tables have captions + scoped headers;
filters labelled; record/evidence rows are real buttons with accessible names;
copy buttons labelled with the hash they copy; detail sections headed.

## 19. Security
Stage-02 client; backend is the authorization boundary; ids path-encoded;
free-form dicts render scalars only (no raw dumps, no hidden metadata
leakage); model/backend text as text; hashes byte-accurate; search values go
through normal query encoding.

## 20. Performance
Server pagination (50/page); detail/evidence/report-sections on demand;
no full-history fetch; no per-row prefetch; tab-local queries only.

## 21. Trust terminology
Used: audit record, hash-chain integrity check, associated evidence, recorded
actor, stored report. Banned and absent: healthy (as a default), verified
truth, tamper-proof, 100% integrity, encrypted (for hashes), legally valid,
forensically proven, outcome (no such field).

## 22. Backend limitations
- `invalid` is `max(total, 1)` on compromise (shown as-is).
- No integrity timestamp; no per-record verification proof beyond the chain.
- `metadata`/`details` non-scalars have no UI; report section `metrics` dicts
  have no UI.
- Store durability is deployment-dependent (as with other modules).

## 23. Deferred features
Decision lineage DAG surface; manual record/evidence creation (trail-pollution
risk — needs product + authorization review, not just endpoints); report
export (no backend support); `after/before` presets; evidence content viewer
for large payloads.
