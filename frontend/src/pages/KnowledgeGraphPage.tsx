import { useMemo, useState } from "react";
import { Card, CardHeader } from "@/components/ui/Card";
import { Badge } from "@/components/ui/Badge";
import { Skeleton } from "@/components/ui/Skeleton";
import { ErrorState } from "@/components/ui/ErrorState";
import { EmptyState } from "@/components/ui/EmptyState";
import { Metric } from "@/components/ui/Metric";
import { useQuery } from "@tanstack/react-query";
import { getGraphStats, getGraphNodes, getGraphImpact } from "@/services/api/knowledgeGraphApi";
import type { GraphNode } from "@/types";

export function KnowledgeGraphPage() {
  const { data: stats, isLoading: sLoading, isError: sError, refetch: sRefetch } = useQuery({
    queryKey: ["kg", "stats"], queryFn: getGraphStats,
  });
  const { data: nodes, isLoading: nLoading, isError: nError, refetch: nRefetch } = useQuery({
    queryKey: ["kg", "nodes"], queryFn: getGraphNodes,
  });
  const [selectedNode, setSelectedNode] = useState<string | undefined>();
  const { data: impact, isLoading: iLoading, isError: iError, refetch: iRefetch } = useQuery({
    queryKey: ["kg", "impact", selectedNode ?? "none"],
    queryFn: () => getGraphImpact(selectedNode!),
    enabled: Boolean(selectedNode),
  });
  const [search, setSearch] = useState("");

  const nodeById = useMemo(() => {
    const map = new Map<string, GraphNode>();
    (nodes ?? []).forEach((n) => map.set(n.node_id, n));
    return map;
  }, [nodes]);

  const types = useMemo(() => {
    const counts = new Map<string, number>();
    (nodes ?? []).forEach((n) => counts.set(n.type, (counts.get(n.type) ?? 0) + 1));
    return Array.from(counts.entries()).sort((a, b) => b[1] - a[1]);
  }, [nodes]);

  const filtered = useMemo(() => {
    if (!search) return nodes ?? [];
    const q = search.toLowerCase();
    return (nodes ?? []).filter((n) => n.label?.toLowerCase().includes(q) || n.type?.toLowerCase().includes(q) || n.node_id?.toLowerCase().includes(q));
  }, [nodes, search]);

  const errorAny = sError || nError;

  return (
    <div className="mx-auto grid max-w-7xl grid-cols-1 gap-4 lg:grid-cols-[240px_minmax(0,1fr)_300px]">
      <aside className="space-y-4">
        <Card padding="md">
          <h3 className="text-sm font-semibold text-slate-900 dark:text-slate-100">Entity Types</h3>
          {sLoading || nLoading ? <Skeleton lines={4} className="mt-3" />
          : errorAny ? <ErrorState onRetry={() => { sRefetch(); nRefetch(); }} />
          : <ul className="mt-3 space-y-1.5">
              {types.map(([t, c]) => (
                <li key={t} className="flex items-center justify-between rounded-md bg-slate-50 px-2 py-1 text-xs dark:bg-slate-800/40">
                  <span className="truncate text-slate-700 dark:text-slate-200">{t}</span>
                  <Badge tone="neutral" size="sm">{c}</Badge>
                </li>
              ))}
              {!types.length ? <li key="empty" className="text-xs text-slate-500">No nodes yet.</li> : null}
            </ul>
          }
        </Card>
      </aside>

      <div className="space-y-4">
        <section className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <Metric label="Nodes" value={stats?.total_nodes ?? "—"} hint="Total entities" />
          <Metric label="Relationships" value={stats?.total_relationships ?? "—"} hint="Edges between entities" />
          <Metric label="Generated at" value={stats ? new Date(stats.generated_at * 1000).toLocaleString() : "—"} hint="Snapshot timestamp" />
        </section>

        <Card padding="md">
          <input
            type="text"
            placeholder="Search entities by name, type, or ID…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full rounded-lg border border-slate-300 px-3 py-2 text-xs dark:border-slate-700 dark:bg-slate-800 dark:text-slate-200"
            aria-label="Search knowledge graph"
          />
        </Card>

        <Card padding="none">
          <CardHeader title="Entities" description="Click to inspect impact"
            actions={<Badge tone="info">{(filtered ?? []).length} entities</Badge>}
          />
          <div className="card-body max-h-[50vh] overflow-y-auto">
            {nLoading ? <Skeleton lines={6} />
            : nError ? <ErrorState onRetry={nRefetch} />
            : !nodes?.length ? <EmptyState title="No nodes yet" />
            : <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
                {filtered.slice(0, 60).map((n) => (
                  <li key={n.node_id}>
                    <button type="button" onClick={() => setSelectedNode(n.node_id)}
                      className={`w-full rounded-lg border px-3 py-2 text-left text-xs transition ${
                        selectedNode === n.node_id
                          ? "border-brand-500 bg-brand-50 dark:bg-brand-950/30"
                          : "border-slate-200 hover:border-brand-300 dark:border-slate-800 dark:hover:border-brand-500"
                      }`}
                    >
                      <p className="truncate text-sm font-semibold text-slate-900 dark:text-slate-100">{n.label}</p>
                      <p className="mt-0.5 truncate text-[10px] text-slate-500">{n.type} · {n.node_id}</p>
                    </button>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>
      </div>

      <aside className="space-y-4">
        <Card padding="none">
          <CardHeader title="Impact Analysis"
            description={selectedNode ? `From ${nodeById.get(selectedNode)?.label ?? selectedNode}` : "Select an entity"}
          />
          <div className="card-body">
            {!selectedNode ? <p className="text-xs text-slate-500">Select any entity to see downstream dependencies and affected nodes.</p>
            : iLoading ? <Skeleton lines={4} />
            : iError ? <ErrorState onRetry={iRefetch} />
            : !impact || !impact.affected?.length ? <EmptyState title="No impact detected" />
            : <ul className="space-y-1.5">
                {impact.affected.slice(0, 15).map((n) => (
                  <li key={n.node_id} className="rounded-md border border-slate-200 px-2 py-1.5 text-xs dark:border-slate-800">
                    <p className="truncate font-medium text-slate-900 dark:text-slate-100">{n.label}</p>
                    <p className="truncate text-[10px] text-slate-500">{n.type}</p>
                  </li>
                ))}
              </ul>
            }
          </div>
        </Card>
        <Card padding="md">
          <h3 className="text-xs font-semibold text-slate-900 dark:text-slate-100">Dependency Analysis</h3>
          <p className="mt-1 text-[11px] text-slate-500">Select an entity to run a BFS traversal and discover downstream impacts across the graph.</p>
        </Card>
      </aside>
    </div>
  );
}
