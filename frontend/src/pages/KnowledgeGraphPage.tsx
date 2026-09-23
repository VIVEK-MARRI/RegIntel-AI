import { useEffect, useMemo, useState } from "react";
import { useParams } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ErrorState } from "@/components/ui/ErrorState";
import { Metric } from "@/components/ui/Metric";
import { Skeleton } from "@/components/ui/Skeleton";
import { GraphView, type GraphViewEdge, type GraphViewNode } from "@/components/kg/GraphView";
import { toNodeView } from "@/adapters/knowledgeGraph";
import { kgKeys } from "@/lib/queryKeys";
import { formatRelative } from "@/lib/format";
import {
  getDependencyAnalysis,
  getGraphImpact,
  getGraphNode,
  getGraphNodes,
  getGraphRelationships,
  getGraphStats,
} from "@/services/api/knowledgeGraphApi";
import type { GraphNode, RelationshipType } from "@/types/api/knowledgeGraph";
import { clsx } from "clsx";

/**
 * Knowledge-graph explorer. Every number comes from its backend field
 * (see docs/KNOWLEDGE_GRAPH_ARCHITECTURE_STAGE09.md):
 * - totals come ONLY from GET /stats (never from rendered rows);
 * - the nodes endpoint returns a bare ARRAY (envelope unwrapped in the
 *   service), so paging is prev/next with a short-page heuristic;
 * - traversal steps carry endpoint IDS only — names resolve through the
 *   fetched node list, falling back to the raw id;
 * - absence of reachable nodes means "none reachable in the stored
 *   graph", never "no real-world effect".
 */

/** Backend RelationshipType enum (app/schemas/knowledge_graph.py). */
const REL_TYPES: RelationshipType[] = ["amends", "references", "supersedes", "affects", "relates_to"];
/** Backend EntityType enum. */
const ENTITY_TYPES = ["regulation", "circular", "amendment", "institution", "topic", "requirement"];

const PAGE_SIZE = 50;
const EDGE_PAGE_SIZE = 100;
const MAX_GRAPH_NODES = 60;
const SEARCH_DEBOUNCE_MS = 300;

type EntityTone = "neutral" | "success" | "warning" | "danger" | "info" | "brand";
const ENTITY_TONE: Record<string, EntityTone> = {
  regulation: "brand",
  circular: "info",
  amendment: "warning",
  institution: "success",
  topic: "neutral",
  requirement: "info",
};
/** Legend swatches mirror the GraphView SVG fills exactly. */
const LEGEND_SWATCH: Record<string, string> = {
  regulation: "border-brand-500 bg-brand-100 dark:bg-brand-950/50",
  circular: "border-sky-500 bg-sky-100 dark:bg-sky-950/50",
  amendment: "border-amber-500 bg-amber-100 dark:bg-amber-950/50",
  institution: "border-emerald-500 bg-emerald-100 dark:bg-emerald-950/50",
  topic: "border-slate-500 bg-slate-200 dark:bg-slate-800",
  requirement: "border-violet-500 bg-violet-100 dark:bg-violet-950/50",
};

const selectClass =
  "rounded-lg border border-slate-200 bg-white px-2 py-2 text-sm text-slate-800 dark:border-slate-700 dark:bg-surface-dark-2 dark:text-slate-100";
const inputClass =
  "w-full rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm text-slate-800 placeholder:text-slate-400 dark:border-slate-700 dark:bg-surface-dark-2 dark:text-slate-100 dark:placeholder:text-slate-500";
const labelClass = "meta-text mb-1 block";

export function KnowledgeGraphPage() {
  const { nodeId: routeNodeId } = useParams();

  const [searchInput, setSearchInput] = useState("");
  const [search, setSearch] = useState("");
  const [entityType, setEntityType] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState<string | null>(routeNodeId ?? null);
  const [depth, setDepth] = useState(3);
  const [relType, setRelType] = useState("");

  // Deep link / refresh: the route param seeds the selection.
  useEffect(() => {
    if (routeNodeId) setSelectedId(routeNodeId);
  }, [routeNodeId]);

  // Debounced server-side name search; typing resets to the first page.
  useEffect(() => {
    const t = window.setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(0);
    }, SEARCH_DEBOUNCE_MS);
    return () => window.clearTimeout(t);
  }, [searchInput]);

  // ---- queries (React Query owns all server state) ----
  const stats = useQuery({ queryKey: kgKeys.stats(), queryFn: getGraphStats });

  const nodesQuery = useMemo(
    () => ({
      entity_type: entityType || undefined,
      name_contains: search || undefined,
      page: page + 1,
      page_size: PAGE_SIZE,
    }),
    [entityType, search, page]
  );
  const nodes = useQuery({ queryKey: kgKeys.nodes(nodesQuery), queryFn: () => getGraphNodes(nodesQuery) });

  const selectedNode = useQuery({
    queryKey: kgKeys.node(selectedId ?? "none"),
    queryFn: () => getGraphNode(selectedId as string),
    enabled: !!selectedId,
  });

  const relQueryOut = useMemo(
    () => ({ source_id: selectedId ?? undefined, rel_type: relType || undefined, page_size: EDGE_PAGE_SIZE }),
    [selectedId, relType]
  );
  const relQueryIn = useMemo(
    () => ({ target_id: selectedId ?? undefined, rel_type: relType || undefined, page_size: EDGE_PAGE_SIZE }),
    [selectedId, relType]
  );
  const edgesOut = useQuery({
    queryKey: kgKeys.relationships({ source_id: selectedId ?? undefined, rel_type: relType || undefined }),
    queryFn: () => getGraphRelationships(relQueryOut),
    enabled: !!selectedId,
  });
  const edgesIn = useQuery({
    queryKey: kgKeys.relationships({ target_id: selectedId ?? undefined, rel_type: relType || undefined }),
    queryFn: () => getGraphRelationships(relQueryIn),
    enabled: !!selectedId,
  });

  const impact = useQuery({
    queryKey: selectedId ? kgKeys.impact(selectedId, depth, relType) : kgKeys.impact("none", depth),
    queryFn: () =>
      getGraphImpact(selectedId as string, {
        max_depth: depth,
        rel_type: (relType || undefined) as RelationshipType | undefined,
      }),
    enabled: !!selectedId,
  });

  const dependency = useQuery({
    queryKey: selectedId ? kgKeys.dependency(selectedId, depth) : kgKeys.dependency("none", depth),
    queryFn: () => getDependencyAnalysis(selectedId as string, depth),
    enabled: !!selectedId,
  });

  // ---- derived ----
  const listNodes: GraphNode[] = nodes.data ?? [];
  const nodeById = useMemo(() => new Map(listNodes.map((n) => [n.node_id, n])), [listNodes]);
  const center: GraphNode | undefined =
    selectedNode.data ?? (selectedId ? nodeById.get(selectedId) : undefined);

  const outEdges = edgesOut.data ?? [];
  const inEdges = edgesIn.data ?? [];

  /** Traversal payloads carry ids only; resolve through fetched nodes, else raw id. */
  const nameById = useMemo(() => {
    const m = new Map<string, string>();
    for (const n of listNodes) m.set(n.node_id, n.name);
    for (const d of [...(dependency.data?.upstream ?? []), ...(dependency.data?.downstream ?? [])]) {
      if (!m.has(d.node_id)) m.set(d.node_id, d.name);
    }
    return m;
  }, [listNodes, dependency.data]);
  const nameOf = (id: string) => nameById.get(id) ?? id;

  const impactDepthById = useMemo(() => {
    const m = new Map<string, number>();
    for (const s of impact.data?.steps ?? []) {
      const prev = m.get(s.to_node_id);
      if (prev === undefined || s.depth < prev) m.set(s.to_node_id, s.depth);
    }
    return m;
  }, [impact.data]);

  const graph = useMemo<{ nodes: GraphViewNode[]; edges: GraphViewEdge[]; total: number; capped: boolean }>(() => {
    if (!center || !selectedId) return { nodes: [], edges: [], total: 0, capped: false };
    const ordered: string[] = [];
    const seen = new Set<string>([selectedId]);
    const push = (id: string) => {
      if (seen.has(id)) return;
      seen.add(id);
      ordered.push(id);
    };
    for (const e of outEdges) push(e.target_id);
    for (const e of inEdges) push(e.source_id);
    for (const s of impact.data?.steps ?? []) {
      if (s.from_node_id === selectedId) push(s.to_node_id);
      else push(s.to_node_id);
    }
    const total = 1 + ordered.length;
    const visible = ordered.slice(0, MAX_GRAPH_NODES - 1);
    const visibleIds = new Set([selectedId, ...visible]);
    const gNodes: GraphViewNode[] = [
      { id: selectedId, label: center.name, type: center.entity_type, depth: 0 },
      ...visible.map((id) => ({
        id,
        label: nameOf(id),
        type: nodeById.get(id)?.entity_type ?? "unknown",
        depth: impactDepthById.get(id) ?? 1,
      })),
    ];
    const gEdges: GraphViewEdge[] = [...outEdges, ...inEdges]
      .filter((e) => visibleIds.has(e.source_id) && visibleIds.has(e.target_id))
      .map((e) => ({ id: e.relationship_id, source: e.source_id, target: e.target_id, type: e.relationship_type }));
    return { nodes: gNodes, edges: gEdges, total, capped: total > gNodes.length };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [center, selectedId, outEdges, inEdges, impact.data, nodeById, impactDepthById]);

  const highlightedIds = useMemo(
    () => new Set(impact.data?.affected_node_ids ?? []),
    [impact.data]
  );

  const hasFilters = searchInput !== "" || entityType !== "";
  const clearFilters = () => {
    setSearchInput("");
    setSearch("");
    setEntityType("");
    setPage(0);
  };

  const shortPage = listNodes.length < PAGE_SIZE;

  return (
    <div className="mx-auto w-full max-w-7xl px-4 py-6 lg:px-6">
      <header>
        <h1 className="page-title">Knowledge Graph</h1>
        <p className="page-description">
          Entities and relationships extracted from regulatory documents. Select an entity to
          inspect it, trace downstream reachability, and review upstream dependencies.
        </p>
      </header>

      {/* metrics — totals from /stats only, never from rendered rows */}
      <section aria-label="Overview" className="mb-6 mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
        {stats.isPending ? (
          <>
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
            <Skeleton className="h-24" />
          </>
        ) : stats.isError ? (
          <div className="sm:col-span-3">
            <ErrorState
              title="Graph statistics unavailable"
              error={stats.error}
              onRetry={() => {
                void stats.refetch();
              }}
            />
          </div>
        ) : (
          <>
            <Metric label="Entities" value={stats.data.total_nodes.toLocaleString()} hint="All entities in the stored graph" />
            <Metric
              label="Relationships"
              value={stats.data.total_relationships.toLocaleString()}
              hint="All relationships in the stored graph"
            />
            <Metric
              label="Snapshot generated"
              value={formatRelative(stats.data.generated_at)}
              hint={`avg degree ${stats.data.average_degree.toFixed(2)} · ${stats.data.connected_components} component(s)`}
            />
          </>
        )}
      </section>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-[300px_minmax(0,1fr)_340px]">
        {/* ---- entity list ---- */}
        <Card className="p-4">
          <h2 className="mb-3 text-sm font-semibold text-slate-900 dark:text-white">Entities</h2>
          <label className={labelClass} htmlFor="kg-search">Search all entities (server)</label>
          <input
            id="kg-search"
            type="search"
            value={searchInput}
            onChange={(e) => setSearchInput(e.target.value)}
            placeholder="Name contains…"
            className={inputClass}
          />
          <div className="mt-3">
            <label className={labelClass} htmlFor="kg-type">Entity type</label>
            <select
              id="kg-type"
              value={entityType}
              onChange={(e) => {
                setEntityType(e.target.value);
                setPage(0);
              }}
              className={clsx(selectClass, "w-full")}
            >
              <option value="">All types</option>
              {ENTITY_TYPES.map((t) => (
                <option key={t} value={t}>{t}</option>
              ))}
            </select>
          </div>
          {hasFilters && (
            <Button variant="ghost" size="sm" className="mt-2" onClick={clearFilters}>
              Clear filters
            </Button>
          )}

          <div className="mt-3" aria-live="polite">
            {nodes.isPending ? (
              <div className="space-y-2">
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
                <Skeleton className="h-12" />
              </div>
            ) : nodes.isError ? (
              <ErrorState
                title="Entities unavailable"
                error={nodes.error}
                onRetry={() => {
                  void nodes.refetch();
                }}
              />
            ) : listNodes.length === 0 ? (
              <EmptyState
                title="No entities match"
                description={hasFilters ? "Adjust the search or type filter." : "The graph has no entities yet."}
              />
            ) : (
              <ul className="max-h-[480px] space-y-1 overflow-y-auto">
                {listNodes.map((n) => {
                  const v = toNodeView(n);
                  const active = v.id === selectedId;
                  return (
                    <li key={v.id}>
                      <button
                        type="button"
                        onClick={() => setSelectedId(v.id)}
                        aria-pressed={active}
                        className={clsx(
                          "w-full rounded-lg border px-3 py-2 text-left transition-colors",
                          active
                            ? "border-brand-500 bg-brand-50 dark:border-brand-400 dark:bg-brand-950/30"
                            : "border-transparent hover:border-slate-200 hover:bg-slate-50 dark:hover:border-slate-700 dark:hover:bg-slate-800/60"
                        )}
                      >
                        <div className="truncate text-sm font-medium text-slate-900 dark:text-white">{v.label}</div>
                        <div className="mt-1">
                          <Badge tone={ENTITY_TONE[v.type] ?? "neutral"}>{v.type}</Badge>
                        </div>
                      </button>
                    </li>
                  );
                })}
              </ul>
            )}
          </div>

          {!nodes.isPending && !nodes.isError && (
            <div className="mt-3 flex items-center justify-between gap-2">
              <span className="meta-text" aria-live="polite">
                Page {page + 1} · {listNodes.length} shown
              </span>
              <div className="flex gap-1">
                <Button variant="ghost" size="sm" disabled={page <= 0} onClick={() => setPage((p) => Math.max(0, p - 1))}>
                  Prev
                </Button>
                <Button variant="ghost" size="sm" disabled={shortPage} onClick={() => setPage((p) => p + 1)}>
                  Next
                </Button>
              </div>
            </div>
          )}
        </Card>

        {/* ---- graph ---- */}
        <Card className="p-4">
          <div className="mb-1 flex flex-wrap items-center gap-2">
            <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Relationship graph</h2>
            {graph.capped && (
              <Badge tone="warning">
                Showing {graph.nodes.length} of {graph.total} — refine depth or type
              </Badge>
            )}
          </div>
          {!selectedId || !center ? (
            <EmptyState
              title="Select an entity"
              description="Pick an entity from the list to center the graph and load its details, reachability, and dependencies."
            />
          ) : edgesOut.isError || edgesIn.isError ? (
            <ErrorState
              title="Relationships unavailable"
              error={edgesOut.error ?? edgesIn.error}
              onRetry={() => {
                void edgesOut.refetch();
                void edgesIn.refetch();
              }}
            />
          ) : edgesOut.isPending || edgesIn.isPending ? (
            <Skeleton className="h-[300px] lg:h-[420px]" />
          ) : (
            <GraphView
              nodes={graph.nodes}
              edges={graph.edges}
              selectedId={selectedId}
              highlightedIds={highlightedIds}
              onSelectNode={(id) => setSelectedId(id)}
            />
          )}

          {/* legend — color is redundant with adjacent text labels */}
          <div className="mt-3 border-t border-slate-100 pt-3 dark:border-slate-800">
            <h3 className="meta-text mb-2">Legend</h3>
            <ul className="flex flex-wrap gap-x-3 gap-y-1.5 text-xs text-slate-600 dark:text-slate-300">
              {ENTITY_TYPES.map((t) => (
                <li key={t} className="flex items-center gap-1.5">
                  <span aria-hidden className={clsx("inline-block h-2.5 w-2.5 rounded-full border", LEGEND_SWATCH[t])} />
                  {t}
                </li>
              ))}
              <li className="flex items-center gap-1.5">
                <span aria-hidden className="inline-block h-2.5 w-2.5 rounded-full border-2 border-amber-500" />
                impact-reachable
              </li>
            </ul>
            <p className="meta-text mt-2">
              Inner ring = direct neighbors · outer ring = reachable within depth · arrows point from
              source to target. Every encoding here is repeated as text in the inspector and impact lists.
            </p>
          </div>
        </Card>

        {/* ---- inspector + analysis ---- */}
        <div className="flex flex-col gap-4">
          <Card className="p-4">
            <div className="mb-2 flex items-center justify-between">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Inspector</h2>
              {selectedId && (
                <Button variant="ghost" size="sm" onClick={() => setSelectedId(null)}>
                  Clear selection
                </Button>
              )}
            </div>
            {!selectedId ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">Nothing selected.</p>
            ) : selectedNode.isPending ? (
              <div className="space-y-2">
                <Skeleton className="h-6 w-2/3" />
                <Skeleton className="h-16" />
                <Skeleton className="h-6 w-1/2" />
              </div>
            ) : selectedNode.isError ? (
              <ErrorState
                title="Entity unavailable"
                error={selectedNode.error}
                onRetry={() => {
                  void selectedNode.refetch();
                }}
              />
            ) : selectedNode.data ? (
              (() => {
                const v = toNodeView(selectedNode.data);
                return (
                  <dl className="space-y-2 text-sm">
                    <div>
                      <dt className="meta-text">Name</dt>
                      <dd className="font-semibold text-slate-900 dark:text-white">{v.label}</dd>
                    </div>
                    <div>
                      <dt className="meta-text">Type</dt>
                      <dd><Badge tone={ENTITY_TONE[v.type] ?? "neutral"}>{v.type}</Badge></dd>
                    </div>
                    <div>
                      <dt className="meta-text">Node ID</dt>
                      <dd className="break-all font-mono text-xs text-slate-600 dark:text-slate-300">{v.id}</dd>
                    </div>
                    <div>
                      <dt className="meta-text">Source</dt>
                      <dd className="text-slate-700 dark:text-slate-200">{selectedNode.data.source}</dd>
                    </div>
                    {v.description && (
                      <div>
                        <dt className="meta-text">Description</dt>
                        <dd className="text-slate-700 dark:text-slate-200">{v.description}</dd>
                      </div>
                    )}
                    {v.tags.length > 0 && (
                      <div>
                        <dt className="meta-text">Tags</dt>
                        <dd className="flex flex-wrap gap-1">
                          {v.tags.map((t) => (
                            <Badge key={t}>{t}</Badge>
                          ))}
                        </dd>
                      </div>
                    )}
                    <div className="grid grid-cols-2 gap-2">
                      <div>
                        <dt className="meta-text">Created</dt>
                        <dd className="text-slate-700 dark:text-slate-200">
                          {formatRelative(selectedNode.data.created_at)}
                        </dd>
                      </div>
                      <div>
                        <dt className="meta-text">Updated</dt>
                        <dd className="text-slate-700 dark:text-slate-200">
                          {formatRelative(selectedNode.data.updated_at)}
                        </dd>
                      </div>
                    </div>
                  </dl>
                );
              })()
            ) : null}

            {/* relationships — explicit textual lists, directional */}
            {selectedId && (
              <div className="mt-4 border-t border-slate-100 pt-3 dark:border-slate-800">
                <h3 className="mb-2 text-sm font-semibold text-slate-900 dark:text-white">
                  Relationships
                  <span className="meta-text ml-2 font-normal">
                    {outEdges.length} outgoing · {inEdges.length} incoming
                  </span>
                </h3>
                <label className={labelClass} htmlFor="kg-reltype">Relationship type</label>
                <select
                  id="kg-reltype"
                  value={relType}
                  onChange={(e) => setRelType(e.target.value)}
                  className={clsx(selectClass, "w-full")}
                >
                  <option value="">All types</option>
                  {REL_TYPES.map((t) => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
                {(edgesOut.isPending || edgesIn.isPending) && (
                  <div className="mt-2 space-y-2">
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                  </div>
                )}
                {!edgesOut.isPending && !edgesIn.isPending && !(edgesOut.isError || edgesIn.isError) && (
                  <>
                    {outEdges.length === 0 && inEdges.length === 0 ? (
                      <p className="mt-2 text-sm text-slate-500 dark:text-slate-400">
                        No relationships{relType ? ` of type “${relType}”` : ""} for this entity.
                      </p>
                    ) : (
                      <div className="mt-2 space-y-3">
                        {outEdges.length > 0 && (
                          <div>
                            <h4 className="meta-text mb-1">Outgoing ({outEdges.length})</h4>
                            <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                              {outEdges.map((e) => (
                                <li key={e.relationship_id} className="flex items-center gap-1.5">
                                  <Badge className="shrink-0">{e.relationship_type}</Badge>
                                  <button
                                    type="button"
                                    onClick={() => setSelectedId(e.target_id)}
                                    className="truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                                    title={nameOf(e.target_id)}
                                  >
                                    → {nameOf(e.target_id)}
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                        {inEdges.length > 0 && (
                          <div>
                            <h4 className="meta-text mb-1">Incoming ({inEdges.length})</h4>
                            <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                              {inEdges.map((e) => (
                                <li key={e.relationship_id} className="flex items-center gap-1.5">
                                  <Badge className="shrink-0">{e.relationship_type}</Badge>
                                  <button
                                    type="button"
                                    onClick={() => setSelectedId(e.source_id)}
                                    className="truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                                    title={nameOf(e.source_id)}
                                  >
                                    ← {nameOf(e.source_id)}
                                  </button>
                                </li>
                              ))}
                            </ul>
                          </div>
                        )}
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </Card>

          {/* ---- impact ---- */}
          {selectedId && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Downstream reachability</h2>
              <p className="meta-text mb-2 mt-0.5">
                Entities reachable from the selection within N hops. Absence means “none reachable in
                the stored graph”, not “no real-world effect”.
              </p>
              <label className={labelClass} htmlFor="kg-depth">Traversal depth (1–10)</label>
              <input
                id="kg-depth"
                type="number"
                min={1}
                max={10}
                value={depth}
                onChange={(e) => setDepth(Math.min(10, Math.max(1, Number(e.target.value) || 1)))}
                className={inputClass}
              />
              <div className="mt-2" aria-live="polite">
                {impact.isPending ? (
                  <div className="space-y-2">
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                  </div>
                ) : impact.isError ? (
                  <ErrorState
                    title="Reachability unavailable"
                    error={impact.error}
                    onRetry={() => {
                      void impact.refetch();
                    }}
                  />
                ) : impact.data ? (
                  impact.data.affected_node_ids.length === 0 ? (
                    <EmptyState
                      title="None reachable"
                      description={`No entities reachable within ${impact.data.max_depth_reached} hop(s)${relType ? ` via “${relType}”` : ""}.`}
                    />
                  ) : (
                    <>
                      <p className="mb-2 text-sm text-slate-700 dark:text-slate-200">
                        <strong>{impact.data.affected_node_ids.length}</strong> reachable ·{" "}
                        {impact.data.total_paths} path(s) · max depth {impact.data.max_depth_reached}
                      </p>
                      {impact.data.steps.length > 0 && (
                        <ul className="max-h-56 space-y-1 overflow-y-auto text-sm">
                          {impact.data.steps.map((s, i) => (
                            <li key={`${s.from_node_id}-${s.to_node_id}-${i}`} className="flex flex-wrap items-center gap-1.5">
                              <Badge className="shrink-0">{s.relationship_type}</Badge>
                              <span className="truncate text-slate-700 dark:text-slate-200" title={nameOf(s.from_node_id)}>
                                {nameOf(s.from_node_id)}
                              </span>
                              <span aria-hidden="true" className="text-slate-400">→</span>
                              <button
                                type="button"
                                onClick={() => setSelectedId(s.to_node_id)}
                                className="min-w-0 flex-1 truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                                title={nameOf(s.to_node_id)}
                              >
                                {nameOf(s.to_node_id)}
                              </button>
                              <span className="meta-text shrink-0">depth {s.depth}</span>
                            </li>
                          ))}
                        </ul>
                      )}
                    </>
                  )
                ) : null}
              </div>
            </Card>
          )}

          {/* ---- dependencies ---- */}
          {selectedId && (
            <Card className="p-4">
              <h2 className="text-sm font-semibold text-slate-900 dark:text-white">Upstream dependencies</h2>
              <p className="meta-text mb-2 mt-0.5">
                Entities the selection depends on (reverse traversal), plus detected cycles.
              </p>
              <div aria-live="polite">
                {dependency.isPending ? (
                  <div className="space-y-2">
                    <Skeleton className="h-8" />
                    <Skeleton className="h-8" />
                  </div>
                ) : dependency.isError ? (
                  <ErrorState
                    title="Dependencies unavailable"
                    error={dependency.error}
                    onRetry={() => {
                      void dependency.refetch();
                    }}
                  />
                ) : dependency.data ? (
                  <>
                    {dependency.data.cycles_detected > 0 && (
                      <p className="mb-2 rounded-lg border border-amber-300 bg-amber-50 p-2 text-sm text-amber-800 dark:border-amber-700 dark:bg-amber-950/40 dark:text-amber-200">
                        <strong>{dependency.data.cycles_detected} dependency cycle(s) detected</strong>
                        {" "}— the backend reports a count, not the cycle paths.
                      </p>
                    )}
                    {dependency.data.upstream.length === 0 && dependency.data.downstream.length === 0 ? (
                      <EmptyState
                        title="No dependencies traced"
                        description={`Nothing upstream or downstream within ${depth} hop(s).`}
                      />
                    ) : (
                      <div className="space-y-3">
                        {dependency.data.upstream.length > 0 && (
                          <div>
                            <h3 className="meta-text mb-1">
                              Upstream — depends on ({dependency.data.upstream.length})
                            </h3>
                            <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                              {dependency.data.upstream.map((d) => {
                                const v = toNodeView(d);
                                return (
                                  <li key={v.id} className="flex items-center gap-1.5">
                                    <Badge tone={ENTITY_TONE[v.type] ?? "neutral"} className="shrink-0">{v.type}</Badge>
                                    <button
                                      type="button"
                                      onClick={() => setSelectedId(v.id)}
                                      className="truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                                      title={v.label}
                                    >
                                      {v.label}
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}
                        {dependency.data.downstream.length > 0 && (
                          <div>
                            <h3 className="meta-text mb-1">Downstream — required by ({dependency.data.downstream.length})</h3>
                            <ul className="max-h-40 space-y-1 overflow-y-auto text-sm">
                              {dependency.data.downstream.map((d) => {
                                const v = toNodeView(d);
                                return (
                                  <li key={v.id} className="flex items-center gap-1.5">
                                    <Badge tone={ENTITY_TONE[v.type] ?? "neutral"} className="shrink-0">{v.type}</Badge>
                                    <button
                                      type="button"
                                      onClick={() => setSelectedId(v.id)}
                                      className="truncate text-left text-brand-700 hover:underline dark:text-brand-300"
                                      title={v.label}
                                    >
                                      {v.label}
                                    </button>
                                  </li>
                                );
                              })}
                            </ul>
                          </div>
                        )}
                        <p className="meta-text">
                          Longest chain: {dependency.data.max_chain_length} hop(s) · depth limit {depth}
                        </p>
                      </div>
                    )}
                  </>
                ) : null}
              </div>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
