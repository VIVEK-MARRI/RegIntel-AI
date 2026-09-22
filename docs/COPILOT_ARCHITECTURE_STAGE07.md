# Copilot Architecture — STAGE 07

## 1. Product purpose

Evidence-grounded regulatory Q&A: ask → cited answer → inspect sources →
verify signals → continue, with conversation history that survives reloads.

## 2. Request lifecycle

```
User question (composer: mode + textarea, Enter to send)
  → CopilotPage.runQuery (single AbortController, generation-safe)
  → copilotApi.queryCopilot (POST /copilot/query, 120s timeout, signal)
  → backend orchestration (retrieval + answer + citations + signals)
  → CopilotResponse (blocking, complete)
  → toAssistantMessage (adapter)
  → fresh rich message appended; sessions list invalidated
```

No streaming anywhere. The pending phase shows "Working on your
answer…" + Cancel; it is labeled as waiting, never as streaming.

## 3. Conversation architecture

- List: `GET /conversations` (paginated; title/count/preview/status).
- Detail: `GET /conversations/:id` (full turns, plain messages).
- Create: implicit — first `POST /copilot/query` without an id makes the
  backend create one; the UI navigates to it (`replace`).
- Delete: `DELETE /conversations/:id?hard=true` behind a confirm dialog;
  leaving an active deleted conversation routes to `/copilot`.
- No rename endpoint exists → no rename UI (explicitly deferred).
- Deep links (`/copilot/:conversationId`) load that conversation's
  history; unknown ids show the empty state, never another chat.

## 4. Query/cache architecture

Canonical keys (`copilotKeys`): `sessions`, `messages(id)`, plus a
fire-and-forget `health` warm-up. History is NEVER mirrored into
`useState`. Transient UI state only: `pendingUser` echo, `fresh` rich
answers, `failed` retry payload, per-message votes.

## 5. Request transport

Blocking `POST /copilot/query` with `LONG_TIMEOUT_MS` + caller
`AbortSignal`. No SSE/WebSocket/fetch-streaming is used — deliberately
(see §6).

## 6. Streaming protocol

**No streaming protocol is integrated.** Backend SSE exists only at
`POST /answer/stream`, which is a different feature: it requires
caller-supplied `chunks[]` (422 otherwise) and emits raw generation
tokens with no conversation, citations, confidence, memory, or sources.
Wiring it into Copilot would discard the evidence contract, so Copilot
stays honestly blocking. Fake client-side token animation is banned.

## 7. Message lifecycle

`idle → sending (pending echo + working row) → completed (rich message)
| failed (error bubble + Retry/Dismiss) | cancelled (quiet, input
restored)`. One active request per composer; send disabled while
pending; late completions after switch/unmount/cancel are discarded.

## 8. Citation model

Backend `citations: AnnotatedAnswer` OBJECT (never an array):
`executive_summary`/`detailed_explanation` (annotated text),
`supporting_evidence[]` (chunk content/score/source/section),
`key_regulatory_references[]` (strings),
`references[]` (`citation_id/chunk_id/document_id/document_title/
source/page_number/url/excerpt`). Rendered numbered `[1..n]` with
document, page, source, and excerpt. No confidence percentages are
invented (the object carries none).

## 9. Evidence model

Two real shapes: `supporting_evidence` chunks (content/score/section)
and `sources: SourceAttribution[]` (`document_title/similarity/
confidence-enum/section/excerpt`). Evidence cards show supported
metadata only; page/section jumps don't exist, so nothing links
anywhere fake.

## 10. Confidence/review model

Rendered exactly as provided: `confidence_score` (0–1) +
`confidence_level` (high/medium/low), `faithfulness_score`,
`hallucination_detected` + `hallucination_risk_level` (badge ONLY when
detected), `latency_ms`. No "Verified" badge exists — verification is
expressed through citations + faithfulness, never a fabricated seal.
Scores are shown without claiming they mean "probability correct".

## 11. Error handling

`ApiClientError` → inline error bubble (`role="alert"`) with the backend
detail (422 policy blocks read distinctly from outages), Retry (same
payload, no duplicate echo) + Dismiss. History failures use `ErrorState`
+ retry. No tokens/stacks leak; no `[object Object]`.

## 12. Retry behavior

Retry reuses `{query, mode, conversationId}` and replaces the failed
state (no duplicate user bubbles, no duplicate assistant messages).
Success invalidates the sessions list only.

## 13. Cancellation

AbortController per request: Cancel button, conversation switch,
unmount, and logout all abort. Abort rejects the fetch → quiet reset +
input text restored. The backend has NO cancel endpoint: in-flight
server work may complete unseen — documented, not hidden.

## 14. Timestamp handling

All timestamps via `formatRelative`/`toMillis`: ISO strings
(conversations, answers), epoch-tolerant, null-safe. `Invalid Date`
and raw values can never render (tested).

## 15. Mobile strategy

Stage 04 drawer reused verbatim for sessions (same component/data);
chat full-width; citation/evidence cards stack; composer always
visible; verified 390/768/1024/1440 with zero overflow.

## 16. Accessibility strategy

Labeled composer + Send; `role=log` + `aria-live=polite` announces
completed answers (never token spam); error `role=alert`; mode buttons
`aria-pressed`; feedback buttons labeled + `aria-pressed`; citations in
labeled sections; keyboard send (Enter/Shift+Enter); focus stays put
(no yank); drawer semantics from Stage 04.

## 17. Security considerations

Bearer via the Stage 02 client (memory token); conversation ids
path-encoded; no refresh tokens in components; no `dangerouslySetInnerHTML`
anywhere (plain-text rendering); user text rendered as text; backend
remains the authorization boundary; citation presence is not a
security claim.

## 18. Cache invalidation matrix

| Mutation | Invalidates | Deliberately not |
|---|---|---|
| send (success) | `copilot.sessions` | `copilot.messages(id)` — backend stores plain turns; refetch would duplicate the echo |
| delete conversation | `copilot.sessions` | current messages (route leaves) |
| feedback vote | nothing (local vote state) | server is source on reload |
| conversation switch | — (key change fetches) | manual cache writes |

## 19. Backend limitations

- Blocking only on the copilot path; no cancel endpoint.
- History stores PLAIN turns: rich answers (citations/signals) exist
  only in-session; reloads show text + timestamps (honest, documented
  in-UI by absence of fabricated sections).
- No rename, no message pagination params beyond defaults, no per-user
  conversation filter used (`user_id` optional, unwired).
- `summarise`/`search` return partial envelopes (`answer.summary` /
  `answer.sources`, citations null) — rendered conditionally.
- Prompt-injection rejections surface as 422 with backend detail.

## 20. Known deferred features

Rename, message search/filter, per-message permalinks, streaming (needs
a citations-preserving protocol), prompt library, follow-up suggestions,
conversation export, feedback history UI.

```mermaid
User
 |
 | question (+ mode)
 v
CopilotPage.runQuery (AbortController, single active request)
 |
 v
copilotApi.queryCopilot --> POST /copilot/query (blocking, Bearer, 120s)
 |
 v
retrieval + orchestration (backend)
 |
 v
CopilotResponse: answer + citations(object) + sources + signals
 |
 v
toAssistantMessage (adapter: modes, history-safe plain fallback)
 |
 v
fresh rich message + citations/evidence/confidence/memory render
 |
 v
User (retry / cancel / vote / delete / continue)
```
