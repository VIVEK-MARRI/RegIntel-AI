import { useEffect, useRef, useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { useQuery, useMutation } from "@tanstack/react-query";
import { getCopilotHealth, getSessions, getMessages, queryCopilot } from "@/services/api/copilotApi";
import type { CopilotMessage, CopilotResponsePayload, CopilotCitation, CopilotAttribution, AgentContributionItem, MemoryContext, ChatSession } from "@/types";
import { useNavigate, useParams } from "react-router-dom";
import { formatDurationMs, formatPercent } from "@/lib/format";
import { useToast } from "@/providers/ToastProvider";
import { useQueryClient } from "@tanstack/react-query";

const SUGGESTED = [
  "Summarise the latest SEBI circulars on insider trading",
  "What are our KYC renewal obligations for the next 90 days?",
  "Draft a compliance memo on data localisation requirements",
  "Identify risk drivers for our outsourcing arrangements",
  "Compare FEMA vs RBI reporting thresholds for FY26",
];

export function CopilotPage() {
  const { conversationId } = useParams<{ conversationId: string }>();
  const navigate = useNavigate();
  const qc = useQueryClient();
  const toast = useToast();

  const { data: sessions, isLoading: sessionsLoading, isError: sessionsError, refetch: refetchSessions } = useQuery({
    queryKey: ["copilot", "sessions"],
    queryFn: getSessions,
  });

  useQuery({
    queryKey: ["copilot", "health"],
    queryFn: getCopilotHealth,
    staleTime: 60_000,
  });

  const { data: messagesData, isLoading: messagesLoading, isError: messagesError, refetch: refetchMessages } = useQuery({
    queryKey: ["copilot", "messages", conversationId ?? "none"],
    queryFn: () => getMessages(conversationId),
    enabled: Boolean(conversationId),
  });

  const query = useMutation({
    mutationFn: queryCopilot,
    onSuccess: () => qc.invalidateQueries({ queryKey: ["copilot", "sessions"] }),
  });

  const [input, setInput] = useState("");
  const [messages, setMessages] = useState<CopilotMessage[]>([]);
  const [streaming, setStreaming] = useState(false);
  const scrollerRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (messagesData?.items?.length) {
      setMessages(messagesData.items);
    } else if (!conversationId) {
      setMessages([]);
    }
  }, [messagesData, conversationId]);

  useEffect(() => {
    scrollerRef.current?.scrollTo({
      top: scrollerRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages.length, streaming]);

  async function handleSend() {
    const q = input.trim();
    if (!q) return;
    setInput("");
    const userMsg: CopilotMessage = { role: "user", content: q, timestamp: new Date().toISOString() };
    setMessages((m) => [...m, userMsg]);
    setStreaming(true);
    try {
      const result = await query.mutateAsync({ query: q, conversation_id: conversationId, mode: "answer" });
      if (!conversationId) {
        navigate(`/copilot/${result.conversation_id}`, { replace: true });
      }
      setMessages((m) => [...m, buildAssistantMessage(result)]);
    } catch (err) {
      toast.push({ title: "Copilot request failed", description: err instanceof Error ? err.message : "Unexpected error", tone: "danger" });
    } finally {
      setStreaming(false);
    }
  }

  return (
    <div className="mx-auto grid h-full max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)]">
      <SessionList
        sessions={sessions?.items}
        isLoading={sessionsLoading}
        error={sessionsError}
        activeId={conversationId}
        onSelect={(id) => navigate(`/copilot/${id}`)}
        onRetry={refetchSessions}
        onNew={() => { setMessages([]); navigate("/copilot"); }}
      />
      <Card padding="none" className="flex h-[calc(100vh-7rem)] flex-col">
        <CardHeader title="Copilot" description="Ask compliance questions with citations and source attribution." />
        <div ref={scrollerRef} className="flex-1 overflow-y-auto px-5 py-4" role="log" aria-live="polite">
          {conversationId && messagesLoading ? (
            <div className="space-y-4 p-4"><Skeleton lines={4} /></div>
          ) : messagesError ? (
            <ErrorState title="Failed to load messages" onRetry={refetchMessages} />
          ) : messages.length === 0 && !streaming ? (
            <EmptyState title="Ask the RegIntel Copilot" description="Ask regulatory, compliance, or risk questions and get citation-backed answers." />
          ) : (
            <ul className="space-y-4">
              {messages.map((m, i) => (<MessageBubble key={i} message={m} />))}
              {streaming ? (
                <li key="streaming" className="flex items-start gap-3">
                  <Avatar role="assistant" />
                  <div className="rounded-2xl border border-slate-200 bg-white px-4 py-3 text-sm shadow-elevated dark:border-slate-800 dark:bg-surface-dark-2">
                    <Skeleton lines={2} />
                  </div>
                </li>
              ) : null}
            </ul>
          )}
        </div>
        <div className="border-t border-slate-200 p-4 dark:border-slate-800">
          <div className="mb-2 flex flex-wrap gap-2">
            {SUGGESTED.map((s) => (
              <button key={s} type="button" onClick={() => setInput(s)}
                className="rounded-full border border-slate-200 bg-white px-3 py-1 text-[11px] font-medium text-slate-600 transition hover:border-brand-300 hover:text-brand-700 dark:border-slate-700 dark:bg-surface-dark-3 dark:text-slate-300 dark:hover:border-brand-500 dark:hover:text-brand-300"
              >{s}</button>
            ))}
          </div>
          <form onSubmit={(e) => { e.preventDefault(); handleSend(); }} className="flex items-end gap-2">
            <textarea className="input min-h-[64px] flex-1 resize-none" placeholder="Ask anything about regulations, compliance, or risk…" value={input}
              onChange={(e) => setInput(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); handleSend(); } }}
              rows={2} aria-label="Copilot prompt"
            />
            <Button type="submit" variant="primary" loading={streaming} disabled={!input.trim()}>Send</Button>
          </form>
        </div>
      </Card>
    </div>
  );
}

function SessionList({ sessions, isLoading, error, activeId, onSelect, onNew, onRetry }: {
  sessions?: ChatSession[]; isLoading: boolean; error: boolean; activeId?: string;
  onSelect: (id: string) => void; onNew: () => void; onRetry: () => void;
}) {
  return (
    <Card padding="none" className="hidden h-[calc(100vh-7rem)] flex-col lg:flex">
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
              <li key={s.conversation_id}>
                <button type="button" onClick={() => onSelect(s.conversation_id)}
                  className={`w-full rounded-lg px-3 py-2 text-left text-xs transition ${
                    activeId === s.conversation_id
                      ? "bg-brand-50 text-brand-700 dark:bg-brand-900/30 dark:text-brand-300"
                      : "text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
                  }`}
                >
                  <p className="truncate font-medium">{s.title || s.preview || "Conversation"}</p>
                  <p className="truncate text-[10px] opacity-70">{s.updated_at ? new Date(s.updated_at * 1000).toLocaleString() : ""}</p>
                </button>
              </li>
            ))}
          </ul>
        }
      </div>
    </Card>
  );
}

function MessageBubble({ message }: { message: CopilotMessage }) {
  const isUser = message.role === "user";
  return (
    <li className={`flex items-start gap-3 ${isUser ? "flex-row-reverse" : ""}`}>
      <Avatar role={message.role} />
      <div className={`max-w-[85%] space-y-2 rounded-2xl border px-4 py-3 text-sm shadow-elevated ${
        isUser
          ? "border-brand-200 bg-brand-50 text-slate-900 dark:border-brand-900/40 dark:bg-brand-950/30 dark:text-slate-100"
          : "border-slate-200 bg-white text-slate-900 dark:border-slate-800 dark:bg-surface-dark-2 dark:text-slate-100"
      }`}>
        {message.answer_section ? (
          <div className="space-y-3">
            <div>
              <p className="whitespace-pre-wrap leading-relaxed">{message.answer_section.executive_summary}</p>
            </div>
            {message.answer_section.detailed_explanation ? (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">Analysis</p>
                <p className="whitespace-pre-wrap leading-relaxed text-slate-700 dark:text-slate-300">{message.answer_section.detailed_explanation}</p>
              </div>
            ) : null}
            {message.answer_section.supporting_evidence?.length ? (
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-1">Evidence ({message.answer_section.supporting_evidence.length})</p>
                <ul className="space-y-1">
                  {message.answer_section.supporting_evidence.map((ev, i) => (
                    <li key={ev.chunk_id ?? i} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
                      <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">
                        {ev.source ? `[${ev.source}]` : ""} {ev.section ?? ""}
                      </span>
                      <p className="mt-0.5 line-clamp-2 italic text-slate-700 dark:text-slate-300">"{ev.excerpt}"</p>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
            {message.answer_section.key_regulatory_references?.length ? (
              <div className="flex flex-wrap gap-1.5">
                <span className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">References:</span>
                {message.answer_section.key_regulatory_references.map((ref, i) => (
                  <Badge key={i} tone="neutral" size="sm">{ref}</Badge>
                ))}
              </div>
            ) : null}
          </div>
        ) : (
          <p className="whitespace-pre-wrap leading-relaxed">{message.content}</p>
        )}
        {!isUser ? (
          <div className="space-y-3 pt-2">
            {message.citations?.length ? <CitationList citations={message.citations} /> : null}
            {message.sources?.length ? <SourceList sources={message.sources} /> : null}
            <Indicators confidence={message.confidence_score} faithfulness={message.faithfulness_score}
              hallucinationRisk={message.hallucination_risk_level} hallucinationDetected={message.hallucination_detected} latency={message.latency_ms} />
            {message.agent_contributions?.length ? <AgentContributionList contributions={message.agent_contributions} /> : null}
            {message.memory_context ? <MemoryContextView ctx={message.memory_context} /> : null}
          </div>
        ) : null}
      </div>
    </li>
  );
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

function CitationList({ citations }: { citations: CopilotCitation[] }) {
  return (<section>
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Citations ({citations.length})</p>
    <ul className="mt-1.5 space-y-1.5">
      {citations.slice(0, 4).map((c, i) => (
        <li key={c.citation_id ?? `${i}`} className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] text-slate-700 dark:border-slate-800 dark:bg-slate-800/40 dark:text-slate-200">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[10px] text-slate-500 dark:text-slate-400">[{i + 1}] {c.source_label ?? c.document_id ?? c.chunk_id ?? c.citation_id}</span>
            <span className="text-[10px] text-slate-500 dark:text-slate-400">{Math.round((c.confidence ?? 0) * 100)}%</span>
          </div>
          <p className="mt-1 line-clamp-2 italic">"{c.text}"</p>
        </li>
      ))}
    </ul>
  </section>);
}

function SourceList({ sources }: { sources: CopilotAttribution[] }) {
  return (<section>
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Sources ({sources.length})</p>
    <ul className="mt-1.5 flex flex-wrap gap-1.5">
      {sources.slice(0, 6).map((s, i) => (
        <li key={s.source_id ?? `${i}`}>
          <Badge tone="neutral" size="sm">{s.document_title ?? s.document_id ?? s.source_id}</Badge>
        </li>
      ))}
    </ul>
  </section>);
}

function Indicators({ confidence, faithfulness, hallucinationRisk, hallucinationDetected, latency }: {
  confidence?: number; faithfulness?: number; hallucinationRisk?: string; hallucinationDetected?: boolean; latency?: number;
}) {
  return (<section className="flex flex-wrap items-center gap-2 text-[11px]">
    {typeof confidence === "number" ? <Badge tone={confidence > 0.75 ? "success" : confidence > 0.5 ? "warning" : "danger"}>Confidence {formatPercent(confidence)}</Badge> : null}
    {typeof faithfulness === "number" ? <Badge tone={faithfulness > 0.75 ? "success" : "warning"}>Faithfulness {formatPercent(faithfulness)}</Badge> : null}
    {hallucinationDetected ? <Badge tone="danger">Hallucination {hallucinationRisk ?? "detected"}</Badge> : null}
    {typeof latency === "number" ? <Badge tone="neutral">{formatDurationMs(latency)}</Badge> : null}
  </section>);
}

function AgentContributionList({ contributions }: { contributions: AgentContributionItem[] }) {
  return (<section>
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Agent Contributions</p>
    <ul className="mt-1.5 grid grid-cols-1 gap-1.5 sm:grid-cols-2">
      {contributions.map((c, i) => (
        <li key={`${c.agent_name}-${i}`} className="flex items-center gap-2 rounded-lg border border-slate-200 bg-white p-2 text-[11px] dark:border-slate-800 dark:bg-surface-dark-3">
          <span className="flex h-5 w-5 items-center justify-center rounded bg-brand-500 text-[10px] font-bold text-white">{c.agent_name.slice(0, 1).toUpperCase()}</span>
          <div className="min-w-0 flex-1">
            <p className="truncate font-medium text-slate-900 dark:text-slate-100">{c.agent_name}</p>
            <p className="truncate text-[10px] text-slate-500 dark:text-slate-400">{c.capability} · {formatDurationMs(c.duration_ms)}</p>
          </div>
          <Badge tone={c.status === "succeeded" ? "success" : c.status === "failed" ? "danger" : "warning"} size="sm">{Math.round((c.confidence ?? 0) * 100)}%</Badge>
        </li>
      ))}
    </ul>
  </section>);
}

function MemoryContextView({ ctx }: { ctx?: MemoryContext }) {
  if (!ctx) return null;
  const total = (ctx.short_term?.length ?? 0) + (ctx.long_term?.length ?? 0);
  if (total === 0 && (ctx.entities?.length ?? 0) === 0) return null;
  return (<section>
    <p className="text-[10px] font-semibold uppercase tracking-wider text-slate-500 dark:text-slate-400">Memory Context</p>
    <div className="mt-1.5 grid grid-cols-1 gap-2 sm:grid-cols-2">
      {ctx.short_term?.length ? (<div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
        <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">Short-term</p>
        <ul className="mt-1 space-y-1">{ctx.short_term.slice(0, 3).map((m, i) => (<li key={i} className="line-clamp-2 italic">"{m.content}"</li>))}</ul>
      </div>) : null}
      {ctx.long_term?.length ? (<div className="rounded-lg border border-slate-200 bg-slate-50 p-2 text-[11px] dark:border-slate-800 dark:bg-slate-800/40">
        <p className="text-[10px] font-semibold text-slate-500 dark:text-slate-400">Long-term</p>
        <ul className="mt-1 space-y-1">{ctx.long_term.slice(0, 3).map((m, i) => (<li key={i} className="line-clamp-2 italic">"{m.content}"</li>))}</ul>
      </div>) : null}
    </div>
    {ctx.entities?.length ? (<div className="mt-2 flex flex-wrap gap-1.5">{ctx.entities.slice(0, 6).map((e, i) => (<Badge key={i} tone="brand" size="sm">{e}</Badge>))}</div>) : null}
  </section>);
}

function buildAssistantMessage(r: CopilotResponsePayload): CopilotMessage {
  const sections = r.answer && typeof r.answer === "object" ? r.answer : null;
  const text = sections
    ? [sections.executive_summary, sections.detailed_explanation].filter(Boolean).join("\n\n")
    : typeof r.answer === "string"
      ? r.answer
      : "";
  return {
    role: "assistant",
    content: text,
    timestamp: new Date().toISOString(),
    citations: r.citations ?? [],
    sources: r.sources ?? [],
    confidence_score: r.confidence_score,
    confidence_level: r.confidence_level,
    faithfulness_score: r.faithfulness_score,
    hallucination_detected: r.hallucination_detected,
    hallucination_risk_level: r.hallucination_risk_level,
    memory_context: r.memory_context,
    latency_ms: r.latency_ms,
    agent_contributions: r.agent_contributions ?? [],
    answer_section: sections ?? undefined,
  };
}
