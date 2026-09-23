import { useEffect, useMemo, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Dialog } from "@/components/ui/Dialog";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  deleteConversation,
  getCopilotHealth,
  getMessages,
  getSessions,
  queryCopilot,
  submitFeedback,
} from "@/services/api/copilotApi";
import {
  toAssistantMessage,
  toHistoryMessage,
  toSessionItem,
  type SessionListItem,
  type UIMessage,
} from "@/adapters/copilot";
import type {
  CopilotMode,
  MemoryContext,
  ReferenceEntry,
  SourceAttribution,
} from "@/types/api/copilot";
import type { FeedbackType } from "@/types/api/feedback";
import { copilotKeys } from "@/lib/queryKeys";
import { formatDurationMs, formatNumber, formatPercent, formatRelative } from "@/lib/format";
import { useToast } from "@/providers/ToastProvider";
import { ApiClientError } from "@/lib/errors";
import { useNavigate, useParams } from "react-router-dom";

const SUGGESTED = [
  "Summarise the latest SEBI circulars on insider trading",
  "What are our KYC renewal obligations for the next 90 days?",
  "Draft a compliance memo on data localisation requirements",
  "Identify risk drivers for our outsourcing arrangements",
  "Compare FEMA vs RBI reporting thresholds for FY26",
];

const MODES: Array<{ id: CopilotMode; label: string }> = [
  { id: "answer", label: "Answer" },
  { id: "summarise", label: "Summarise" },
  { id: "search", label: "Search" },
];

type SendState =
  | { phase: "idle" }
  | { phase: "sending"; query: string; mode: CopilotMode }
  | { phase: "failed"; query: string; mode: CopilotMode; message: string };

export function CopilotPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const { data: sessions, isLoading: sessionsLoading, isError: sessionsError, refetch: refetchSessions } = useQuery({
    queryKey: copilotKeys.sessions(),
    queryFn: () => getSessions(),
  });

  // Fired for its side effect (warms the copilot service); the result is
  // intentionally unused — no fake health gating.
  useQuery({
    queryKey: ["copilot", "health"],
    queryFn: getCopilotHealth,
    staleTime: 60_000,
  });

  const {
    data: messagesData,
    isLoading: messagesLoading,
    isError: messagesError,
    refetch: refetchMessages,
  } = useQuery({
    queryKey: copilotKeys.messages(conversationId ?? "none"),
    queryFn: () => getMessages(conversationId),
    enabled: Boolean(conversationId),
  });

  const [input, setInput] = useState("");
  const [mode, setMode] = useState<CopilotMode>("answer");
  const [send, setSend] = useState<SendState>({ phase: "idle" });
  // Rich answers received this view. Backend history stores plain turns
  // only, so fresh answers live here until the conversation changes.
  const [fresh, setFresh] = useState<UIMessage[]>([]);
  const [votes, setVotes] = useState<Record<string, FeedbackType>>({});
  const [deleteTarget, setDeleteTarget] = useState<string | null>(null);
  const [deleting, setDeleting] = useState(false);

  const abortRef = useRef<AbortController | null>(null);
  const scrollerRef = useRef<HTMLDivElement | null>(null);
  const stickRef = useRef(true);

  const history = useMemo(
    () => (messagesData?.items ?? []).map(toHistoryMessage),
    [messagesData]
  );

  // Conversation switch / unmount: abort in-flight work, drop transient UI.
  // History comes from the query key change; nothing leaks across views.
  useEffect(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setSend({ phase: "idle" });
    setFresh([]);
  }, [conversationId]);

  useEffect(() => {
    return () => {
      abortRef.current?.abort();
      abortRef.current = null;
    };
  }, []);

  const renderedCount =
    history.length + fresh.length + (send.phase === "sending" ? 1 : 0) + (send.phase === "failed" ? 1 : 0);

  const onScroll = () => {
    const el = scrollerRef.current;
    if (!el) return;
    stickRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
  };

  useEffect(() => {
    if (stickRef.current) {
      scrollerRef.current?.scrollTo({ top: scrollerRef.current.scrollHeight });
    }
  }, [renderedCount]);

  async function runQuery(query: string, requestMode: CopilotMode) {
    const controller = new AbortController();
    abortRef.current?.abort();
    abortRef.current = controller;
    setSend({ phase: "sending", query, mode: requestMode });
    try {
      const result = await queryCopilot(
        { query, conversation_id: conversationId, mode: requestMode },
        { signal: controller.signal }
      );
      // Late completion after a switch/unmount/cancel is impossible here:
      // the effect above aborts in-flight work on every conversationId
      // change and on unmount, and abort rejects the fetch below.
      if (!conversationId && result.conversation_id) {
        navigate(`/copilot/${result.conversation_id}`, { replace: true });
      }
      setFresh((list) => [...list, toAssistantMessage(result)]);
      setSend({ phase: "idle" });
      void qc.invalidateQueries({ queryKey: copilotKeys.sessions() });
      // NOTE: messages are deliberately NOT invalidated here — the backend
      // stores plain turns, and refetching would duplicate the echo below.
    } catch (err) {
      if (controller.signal.aborted) {
        setSend({ phase: "idle" });
        return;
      }
      const message =
        err instanceof ApiClientError
          ? err.message
          : err instanceof Error
            ? err.message
            : "Copilot request failed";
      setSend({ phase: "failed", query, mode: requestMode, message });
    } finally {
      if (abortRef.current === controller) abortRef.current = null;
    }
  }

  function handleSend() {
    const q = input.trim();
    if (!q || send.phase === "sending") return;
    setInput("");
    void runQuery(q, mode);
  }

  function handleCancel() {
    if (send.phase === "sending") setInput(send.query);
    abortRef.current?.abort();
  }

  function handleRetry() {
    if (send.phase !== "failed") return;
    void runQuery(send.query, send.mode);
  }

  async function handleVote(message: UIMessage, vote: FeedbackType) {
    if (!message.requestId || votes[message.requestId]) return;
    try {
      await submitFeedback({
        request_id: message.requestId,
        conversation_id: message.conversationId ?? conversationId,
        feedback_type: vote,
      });
      setVotes((v) => ({ ...v, [message.requestId as string]: vote }));
    } catch (err) {
      toast.push({
        title: "Feedback not recorded",
        description: err instanceof Error ? err.message : "Unexpected error",
        tone: "danger",
      });
    }
  }

  async function handleDelete(id: string) {
    setDeleting(true);
    try {
      await deleteConversation(id);
      setDeleteTarget(null);
      if (id === conversationId) navigate("/copilot");
      await qc.invalidateQueries({ queryKey: copilotKeys.sessions() });
    } catch (err) {
      toast.push({
        title: "Delete failed",
        description: err instanceof Error ? err.message : "Unexpected error",
        tone: "danger",
      });
    } finally {
      setDeleting(false);
    }
  }

  const sending = send.phase === "sending";

  return (
    <div className="mx-auto grid h-full max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <h1 className="sr-only">Copilot</h1>
      <div className="hidden lg:block">
        <SessionList
          sessions={sessions?.items?.map(toSessionItem)}
          isLoading={sessionsLoading}
          error={sessionsError}
          activeId={conversationId}
          onSelect={(id) => navigate(`/copilot/${id}`)}
          onRetry={refetchSessions}
          onNew={() => navigate("/copilot")}
          onDelete={(id) => setDeleteTarget(id)}
        />
      </div>
      <MobileSessions
        sessions={sessions?.items?.map(toSessionItem)}
        isLoading={sessionsLoading}
        error={sessionsError}
        activeId={conversationId}
        onSelect={(id) => navigate(`/copilot/${id}`)}
        onRetry={refetchSessions}
        onNew={() => navigate("/copilot")}
        onDelete={(id) => setDeleteTarget(id)}
      />
      <Card padding="none" className="flex h-[calc(100vh-7rem)] flex-col">
        <CardHeader title="Copilot" description="Ask compliance questions with citations and source attribution." />
        <div
          ref={scrollerRef}
          onScroll={onScroll}
          className="flex-1 overflow-y-auto px-5 py-4"
          role="log"
          aria-live="polite"
          aria-label="Conversation messages"
        >
          {conversationId && messagesLoading ? (
            <div className="space-y-4 p-4"><Skeleton lines={4} /></div>
          ) : messagesError ? (
            <ErrorState title="Failed to load messages" onRetry={refetchMessages} />
          ) : history.length === 0 && fresh.length === 0 && !sending && send.phase !== "failed" ? (
            <EmptyState
              title={conversationId ? "No messages yet" : "Ask the RegIntel Copilot"}
              description={
                conversationId
                  ? "This conversation has no messages yet. Ask below to begin."
                  : "Ask regulatory, compliance, or risk questions and get citation-backed answers."
              }
            />
          ) : (
            <ul className="space-y-4">
              {history.map((m, i) => (
                <MessageBubble key={`h-${i}`} message={m} />
              ))}
              {fresh.map((m, i) => (
                <MessageBubble
                  key={`f-${i}-${m.requestId ?? i}`}
                  message={m}
                  vote={m.requestId ? votes[m.requestId] : undefined}
                  onVote={handleVote}
                />
              ))}
              {send.phase === "sending" ? (
                <>
                  <MessageBubble
                    message={{ role: "user", content: send.query, timestamp: new Date().toISOString() }}
                  />
                  <li className="flex items-start gap-3">
                    <Avatar role="assistant" />
                    <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-elevated dark:border-slate-800 dark:bg-surface-dark-2">
                      <p className="text-xs text-slate-500 dark:text-slate-400">Working on your answer…</p>
                      <div className="mt-2"><Skeleton lines={2} /></div>
                      <Button size="sm" variant="secondary" onClick={handleCancel} className="mt-3">
                        Cancel
                      </Button>
                    </div>
                  </li>
                </>
              ) : null}
              {send.phase === "failed" ? (
                <li>
                  <ErrorState
                    title="Copilot request failed"
                    description={send.message}
                    action={
                      <div className="flex gap-2">
                        <Button size="sm" variant="primary" onClick={handleRetry}>
                          Retry
                        </Button>
                        <Button size="sm" variant="secondary" onClick={() => setSend({ phase: "idle" })}>
                          Dismiss
                        </Button>
                      </div>
                    }
                  />
                </li>
              ) : null}
            </ul>
          )}
        </div>
        <div className="border-t border-slate-200 p-4 dark:border-slate-800">
          <div className="mb-2 flex flex-wrap items-center gap-2">
            <div role="group" aria-label="Response mode" className="flex gap-1">
              {MODES.map((m) => (
                <button
                  key={m.id}
                  type="button"
                  onClick={() => setMode(m.id)}
                  disabled={sending}
                  aria-pressed={mode === m.id}
                  className={`rounded-full border px-3 py-1 text-[11px] font-medium transition ${
                    mode === m.id
                      ? "border-brand-500 bg-brand-50 text-brand-700 dark:border-brand-500 dark:bg-brand-950/30 dark:text-brand-300"
                      : "border-slate-200 bg-white text-slate-600 hover:border-brand-300 dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-300"
                  }`}
                >
                  {m.label}
                </button>
              ))}
            </div>
            <div className="mb-2 flex flex-wrap gap-2">
              {SUGGESTED.map((s) => (
                <button key={s} type="button" onClick={() => setInput(s)} disabled={sending}
                  className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-brand-300 hover:text-brand-700 disabled:opacity-50 dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
                >{s}</button>
              ))}
            </div>
          </div>
          <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex items-end gap-2">
            <textarea className="input min-h-[64px] flex-1 resize-none" placeholder="Ask anything about regulations, compliance, or risk…" value={input}
              onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              rows={2} aria-label="Copilot prompt" disabled={sending}
            />
            <Button type="submit" variant="primary" loading={sending} disabled={!input.trim()}>Send</Button>
          </form>
        </div>
      </Card>
      <Dialog
        open={deleteTarget !== null}
        onClose={() => { if (!deleting) setDeleteTarget(null); }}
        label="Delete conversation"
      >
        <h2 className="section-title" id="delete-conv-title">Delete conversation?</h2>
        <p className="body-text mt-2">This permanently removes the conversation and its history. This cannot be undone.</p>
        <div className="mt-4 flex justify-end gap-2">
          <Button variant="secondary" onClick={() => setDeleteTarget(null)} disabled={deleting}>
            Keep
          </Button>
          <Button
            variant="danger"
            loading={deleting}
            onClick={() => { if (deleteTarget) void handleDelete(deleteTarget); }}
          >
            Delete
          </Button>
        </div>
      </Dialog>
    </div>
  );
}

function SessionList({ sessions, isLoading, error, activeId, onSelect, onNew, onRetry, onDelete, className }: {
  sessions?: SessionListItem[]; isLoading: boolean; error: boolean; activeId?: string;
  onSelect: (id: string) => void; onNew: () => void; onRetry: () => void;
  onDelete: (id: string) => void;
  className?: string;
}) {
  return (
    <Card padding="none" className={`flex h-[calc(100vh-7rem)] flex-col ${className ?? ""}`}>
      <div className="card-header flex-col items-stretch gap-2">
        <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Conversations</h3>
        <Button size="sm" variant="secondary" onClick={onNew}>+ New chat</Button>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {isLoading ? <div className="space-y-2 p-2"><Skeleton lines={3} /></div>
        : error ? <ErrorState title="Could not load conversations" onRetry={onRetry} />
        : !sessions?.length ? <EmptyState title="No conversations yet" description="Start a new chat to begin." />
        : <ul className="space-y-1">
            {sessions.map((s) => (
              <li key={s.id} className="group flex items-center gap-1">
                <button type="button" onClick={() => onSelect(s.id)}
                  className={`min-w-0 flex-1 rounded-lg px-3 py-2 text-left text-xs transition ${
                    activeId === s.id
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  <p className="truncate font-medium">{s.title || s.preview || "Conversation"}</p>
                  <p className="truncate text-[10px] opacity-70">
                    {s.updatedMillis != null ? formatRelative(s.updatedMillis) : ""}
                    {s.messageCount > 0 ? ` · ${s.messageCount} messages` : ""}
                  </p>
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(s.id)}
                  aria-label={`Delete conversation ${s.title || s.preview || s.id}`}
                  className="shrink-0 rounded-md p-1.5 text-slate-400 opacity-0 transition hover:bg-red-50 hover:text-red-600 focus-visible:opacity-100 group-hover:opacity-100 dark:hover:bg-red-950/30 dark:hover:text-red-300"
                >
                  <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
                </button>
              </li>
            ))}
          </ul>
        }
      </div>
    </Card>
  );
}

/**
 * Mobile session access: the same SessionList (same data, same callbacks)
 * inside a drawer. No duplicated conversation state.
 */
function MobileSessions(props: {
  sessions?: SessionListItem[]; isLoading: boolean; error: boolean; activeId?: string;
  onSelect: (id: string) => void; onNew: () => void; onRetry: () => void;
  onDelete: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const closeRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!open) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("keydown", onKey);
    const prevOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    closeRef.current?.focus();
    return () => {
      document.removeEventListener("keydown", onKey);
      document.body.style.overflow = prevOverflow;
    };
  }, [open ]);

  const closeAndSelect = (id: string) => {
    setOpen(false);
    props.onSelect(id);
  };
  const closeAndNew = () => {
    setOpen(false);
    props.onNew();
  };

  return (
    <div className="lg:hidden">
      <Button size="sm" variant="secondary" onClick={() => setOpen(true)} aria-haspopup="dialog">
        Conversations
      </Button>
      {open ? (
        <div className="fixed inset-0 z-40">
          <button
            type="button"
            tabIndex={-1}
            aria-hidden="true"
            onClick={() => setOpen(false)}
            data-testid="copilot-sessions-backdrop"
            className="absolute inset-0 h-full w-full cursor-default bg-slate-950/50"
          />
          <div
            role="dialog"
            aria-modal="true"
            aria-label="Conversations"
            className="absolute inset-y-0 left-0 flex w-72 max-w-[85vw] flex-col bg-white shadow-elevated dark:bg-surface-dark-2"
          >
            <div className="flex items-center justify-end border-b border-slate-200 p-2 dark:border-slate-800">
              <button
                ref={closeRef}
                type="button"
                onClick={() => setOpen(false)}
                aria-label="Close conversations"
                className="rounded-md p-1.5 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 dark:hover:bg-slate-800 dark:hover:text-slate-100"
              >
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
            <div className="min-h-0 flex-1 p-2">
              <SessionList
                {...props}
                className="h-full"
                onSelect={closeAndSelect}
                onNew={closeAndNew}
              />
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function MessageBubble({
  message,
  vote,
  onVote,
}: {
  message: UIMessage;
  vote?: FeedbackType;
  onVote?: (message: UIMessage, vote: FeedbackType) => void;
}) {
  const isUser = message.role === "user";
  return (
    <li className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <Avatar role={message.role} />
      <div className={`max-w-[85%] space-y-2 rounded-2xl border px-4 py-3 text-sm shadow-elevated ${
        isUser
          ? "border-brand-200 bg-brand-50 text-slate-900 dark:border-brand-900/40 dark:bg-brand-950/30 dark:text-slate-100"
          : "border-slate-200 bg-white text-slate-900 dark:border-slate-800 dark:bg-surface-dark-2 dark:text-slate-100"
      }`}>
        <MessageContent message={message} />
        {!isUser ? (
          <div className="space-y-3 pt-2">
            {message.citations?.length ? <CitationList citations={message.citations} /> : null}
            {message.sources?.length ? <SourceList sources={message.sources} /> : null}
            <Indicators
              confidence={message.confidence_score}
              confidenceLevel={message.confidence_level}
              faithfulness={message.faithfulness_score}
              hallucinationRisk={message.hallucination_risk_level}
              hallucinationDetected={message.hallucination_detected}
              latency={message.latency_ms}
            />
            {message.memory_context ? <MemoryContextView ctx={message.memory_context} /> : null}
            {message.requestId && onVote ? (
              <FeedbackRow message={message} vote={vote} onVote={onVote} />
            ) : null}
          </div>
        ) : null}
        <p className="text-[10px] text-slate-400 dark:text-slate-500">
          {formatRelative(message.timestamp)}
        </p>
      </div>
    </li>
  );
}

function MessageContent({ message }: { message: UIMessage }) {
  if (message.mode === "search") {
    const hits = message.searchHits ?? [];
    if (!hits.length) {
      return <p className="whitespace-pre-wrap leading-relaxed text-slate-500">No memory matches found.</p>;
    }
    return (
      <ul className="space-y-1.5">
        {hits.map((h, i) => (
          <li key={h.memory_id || i} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
            <div className="flex items-center justify-between gap-2">
              <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                {h.memory_type || "memory"} · {Math.round(h.score * 100)}% match
              </span>
            </div>
            <p className="mt-1 line-clamp-3 text-slate-700 dark:text-slate-300">{h.content}</p>
            {h.tags.length ? (
              <p className="mt-1 truncate text-[10px] text-slate-500 dark:text-slate-400">{h.tags.join(", ")}</p>
            ) : null}
          </li>
        ))}
      </ul>
    );
  }
  if (message.mode === "summarise") {
    return (
      <p className="whitespace-pre-wrap leading-relaxed">
        {message.summaryText || message.content || "No summary was generated."}
      </p>
    );
  }
  if (message.answer) {
    return (
      <div className="space-y-3">
        <div>
          <p className="whitespace-pre-wrap leading-relaxed">{message.answer.executiveSummary}</p>
        </div>
        {message.answer.detailedExplanation ? (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">Analysis</p>
            <p className="whitespace-pre-wrap leading-relaxed text-slate-700 dark:text-slate-300">{message.answer.detailedExplanation}</p>
          </div>
        ) : null}
        {message.answer.evidence?.length ? (
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">Evidence ({message.answer.evidence.length})</p>
            <ul className="space-y-1">
              {message.answer.evidence.map((ev, i) => (
                <li key={ev.chunk_id ?? i} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
                  <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                    {ev.source ? `[${ev.source}]` : ""} {ev.section ?? ""}
                  </span>
                  <p className="mt-0.5 line-clamp-2 italic text-slate-700 dark:text-slate-300">"{ev.content}"</p>
                </li>
              ))}
            </ul>
          </div>
        ) : null}
        {message.answer.references?.length ? (
          <div className="flex flex-wrap gap-1.5">
            <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">References:</span>
            {message.answer.references.map((ref, i) => (
              <Badge key={i} tone="neutral" size="sm">{ref}</Badge>
            ))}
          </div>
        ) : null}
      </div>
    );
  }
  return <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>;
}

function Avatar({ role }: { role: string }) {
  return (
    <div aria-hidden
      className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
        role === "user"
          ? "bg-slate-200 text-slate-700 dark:bg-slate-700 dark:text-slate-100"
          : "bg-gradient-to-br from-brand-500 to-brand-700 text-white"
      }`}
    >{role === "user" ? "U" : "R"}</div>
  );
}

function CitationList({ citations }: { citations: ReferenceEntry[] }) {
  return (<section aria-label="Citations">
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Citations ({citations.length})</p>
    <ul className="mt-1.5 space-y-1.5">
      {citations.slice(0, 6).map((c, i) => (
        <li key={c.citation_id ?? `${i}`} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-200">
          <p className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
            [{i + 1}] {c.document_title ?? c.document_id ?? c.chunk_id ?? c.citation_id}
            {c.page_number != null ? ` · p. ${c.page_number}` : ""}
            {c.source ? ` · ${c.source}` : ""}
          </p>
          <p className="mt-1 line-clamp-2 italic">"{c.excerpt}"</p>
        </li>
      ))}
    </ul>
  </section>);
}

function SourceList({ sources }: { sources: SourceAttribution[] }) {
  return (<section aria-label="Sources">
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Sources ({sources.length})</p>
    <ul className="mt-1.5 space-y-1.5">
      {sources.slice(0, 6).map((s, i) => (
        <li key={s.attribution_id ?? `${i}`} className="flex flex-wrap items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
          <Badge tone="neutral" size="sm">{s.document_title ?? s.document_id}</Badge>
          <span className="text-slate-500 dark:text-slate-400">
            {s.section} · {Math.round(s.similarity * 100)}% match{s.confidence ? ` · ${s.confidence}` : ""}
          </span>
        </li>
      ))}
    </ul>
  </section>);
}

function Indicators({ confidence, confidenceLevel, faithfulness, hallucinationRisk, hallucinationDetected, latency }: {
  confidence?: number; confidenceLevel?: string; faithfulness?: number;
  hallucinationRisk?: string; hallucinationDetected?: boolean; latency?: number;
}) {
  return (<section className="flex flex-wrap items-center gap-2 text-[11px]" aria-label="Answer signals">
    {typeof confidence === "number" ? (
      <Badge tone={confidence > 0.75 ? "success" : confidence > 0.5 ? "warning" : "danger"}>
        Confidence {formatPercent(confidence)}{confidenceLevel ? ` · ${confidenceLevel}` : ""}
      </Badge>
    ) : null}
    {typeof faithfulness === "number" ? <Badge tone={faithfulness > 0.75 ? "success" : "warning"}>Faithfulness {formatPercent(faithfulness)}</Badge> : null}
    {hallucinationDetected ? <Badge tone="danger">Hallucination {hallucinationRisk ?? "detected"}</Badge> : null}
    {typeof latency === "number" ? <Badge tone="neutral">{formatDurationMs(latency)}</Badge> : null}
  </section>);
}

function MemoryContextView({ ctx }: { ctx: MemoryContext }) {
  const shortTerm = ctx.short_term ?? [];
  const longTerm = ctx.long_term ?? [];
  const retrieved = ctx.retrieval ?? [];
  if (shortTerm.length === 0 && longTerm.length === 0 && retrieved.length === 0) return null;
  return (<section aria-label="Memory context">
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Memory Context</p>
    <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
      {shortTerm.length ? (<div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
        <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">Short-term</p>
        <ul className="mt-1 space-y-1">{shortTerm.slice(0, 3).map((m, i) => (<li key={i} className="line-clamp-2 italic">"{m.content}"</li>))}</ul>
      </div>) : null}
      {longTerm.length ? (<div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
        <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">Long-term</p>
        <ul className="mt-1 space-y-1">{longTerm.slice(0, 3).map((m, i) => (<li key={i} className="line-clamp-2 italic">"{m.content}"</li>))}</ul>
      </div>) : null}
    </div>
    {retrieved.length ? (
      <ul className="mt-2 space-y-1">
        {retrieved.slice(0, 3).map((r, i) => (
          <li key={r.entry?.memory_id ?? i} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
            <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
              retrieved · score {formatNumber(r.score ?? 0, 2)} (0–1 relevance)
            </span>
            <p className="mt-0.5 line-clamp-2 italic text-slate-700 dark:text-slate-300">"{r.entry?.content ?? ""}"</p>
          </li>
        ))}
      </ul>
    ) : null}
  </section>);
}

function FeedbackRow({
  message,
  vote,
  onVote,
}: {
  message: UIMessage;
  vote?: FeedbackType;
  onVote: (message: UIMessage, vote: FeedbackType) => void;
}) {
  return (
    <div className="flex items-center gap-1.5" aria-label="Rate this answer">
      {(["thumbs_up", "thumbs_down"] as FeedbackType[]).map((kind) => {
        const active = vote === kind;
        return (
          <button
            key={kind}
            type="button"
            disabled={vote !== undefined}
            aria-pressed={active}
            aria-label={kind === "thumbs_up" ? "Helpful answer" : "Unhelpful answer"}
            onClick={() => onVote(message, kind)}
            className={`rounded-md p-1.5 text-xs transition disabled:cursor-default ${
              active
                ? "bg-brand-100 text-brand-700 dark:bg-brand-950/40 dark:text-brand-300"
                : "text-slate-400 hover:bg-slate-100 hover:text-slate-700 disabled:opacity-40 dark:hover:bg-slate-800 dark:hover:text-slate-200"
            }`}
          >
            <span aria-hidden>{kind === "thumbs_up" ? "▲" : "▼"}</span>
          </button>
        );
      })}
      {vote ? <span className="text-[10px] text-slate-500 dark:text-slate-400">Thanks — feedback recorded.</span> : null}
    </div>
  );
}
