import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { useAgentMessages, useCollaborations } from "@/hooks/api";
import { formatRelative, formatPercent } from "@/lib/format";

export function AgentCollaborationPage() {
  const collabs = useCollaborations();
  const messages = useAgentMessages();

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_360px]">
      <Card padding="none">
        <CardHeader
          title="Collaborations"
          description="Multi-agent coordination sessions"
        />
        <div className="card-body">
          {collabs.isLoading ? (
            <Skeleton lines={5} />
          ) : collabs.isError ? (
            <ErrorState error={collabs.error} onRetry={() => collabs.refetch()} />
          ) : !collabs.data || collabs.data.length === 0 ? (
            <EmptyState
              title="No collaborations yet"
              description="Run an orchestration to generate cross-agent collaboration records."
            />
          ) : (
            <ul className="space-y-3">
              {collabs.data.map((c) => (
                <li
                  key={c.collaboration_id}
                  className="rounded-xl border border-slate-200 p-3 dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <Badge tone="brand" size="sm">
                      {c.participants.length} agents
                    </Badge>
                    <Badge tone="success" size="sm">
                      Consensus {formatPercent(c.consensus)}
                    </Badge>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {formatRelative(c.created_at)}
                    </span>
                  </div>
                  <p className="mt-1.5 text-sm font-semibold text-slate-900 dark:text-slate-100">
                    {c.topic}
                  </p>
                  <p className="mt-1 text-xs text-slate-600 dark:text-slate-300">
                    {c.result_summary}
                  </p>
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {c.participants.map((p) => (
                      <Badge key={p} tone="neutral" size="sm">
                        {p}
                      </Badge>
                    ))}
                  </div>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>

      <Card padding="none">
        <CardHeader
          title="Live message bus"
          description="Streaming agent-to-agent messages"
          actions={
            <Badge tone="info" dot>
              Live
            </Badge>
          }
        />
        <div className="card-body max-h-[70vh] overflow-y-auto">
          {messages.isLoading ? (
            <Skeleton lines={6} />
          ) : !messages.data || messages.data.length === 0 ? (
            <EmptyState title="No traffic yet" description="Messages will appear in real time." />
          ) : (
            <ul className="space-y-2">
              {messages.data.slice(0, 30).map((m) => (
                <li
                  key={m.message_id}
                  className="rounded-lg border border-slate-200 p-2 text-xs dark:border-slate-800"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-semibold text-slate-900 dark:text-slate-100">
                      {m.from_agent}
                    </span>
                    <span aria-hidden>→</span>
                    <span className="text-slate-600 dark:text-slate-300">
                      {m.to_agent ?? m.channel}
                    </span>
                    <Badge tone="neutral" size="sm">
                      {m.kind}
                    </Badge>
                    <span className="ml-auto text-[10px] text-slate-500 dark:text-slate-400">
                      {formatRelative(m.created_at)}
                    </span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-[11px] text-slate-600 dark:text-slate-300">
                    {JSON.stringify(m.payload).slice(0, 200)}
                  </p>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Card>
    </div>
  );
}
