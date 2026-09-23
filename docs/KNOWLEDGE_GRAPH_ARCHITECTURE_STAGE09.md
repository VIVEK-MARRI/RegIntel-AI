# Knowledge Graph Architecture - STAGE 09

## 1. Product purpose
Explore entities and relationships extracted from regulatory documents: search/filter
the entity list, select an entity to center a relationship graph and inspect it, trace
downstream reachability (impact traversal), and review upstream dependencies
(dependency analysis). The page is read-only — the UI exposes no create/update/delete
because the backend has no UI-consumable mutation contract staged for it here.

## 2. Endpoint inventory
Backend: `app/api/v1/knowledge_graph.py` + `app/schemas/knowledge_graph.py`
(`extra="forbid"`). All routes verified in code; list/impact/dependency shapes also
verified by `src/test/api-contracts.test.tsx` MSW fixtures.

| Method | Path | Frontend use | Notes |
|---|---|---|---|
| GET | `/knowledge-graph/stats` | Overview metrics | `{total_nodes, total_relationships, by_entity_type, by_relationship_type, by_source, average_degree, max_depth, connected_components, generated_at}`; `generated_at` is epoch SECONDS |
| GET | `/knowledge-graph/nodes` | Entity list | Filters `entity_type, source, name_contains, tag`; paging `page` (1-based) + `page_size`; returns a paginated ENVELOPE (service unwraps to a bare array, Stage 02 behavior) |
| GET | `/knowledge-graph/nodes/{node_id}` | Inspector | Single node; unknown id → 404 (inspector error panel, not a crash) |
| GET | `/knowledge-graph/relationships` | Inspector edge lists + graph edges | Filters `source_id, target_id, rel_type` (+ paging); paginated envelope, unwrapped to array |
| POST | `/knowledge-graph/impact-traversal/{id}` | Downstream reachability | Query `max_depth` 1–10 (default 3), optional `rel_type`; unknown node → 400 |
| POST | `/knowledge-graph/dependency-analysis/{id}` | Upstream dependencies | Query `max_depth` 1–10 (default 5); unknown node → 400 |
| GET | `/knowledge-graph/snapshot` | NOT USED | Full export; unbounded for UI use — deliberately not fetched |
| POST/GET | `/knowledge-graph/relationships[/{id}]` (create/single) | NOT USED | No UI affordance in this stage |

## 3. Entity model
Backend `GraphNode`: `{node_id, entity_type, name, description, external_id?, source,
properties, tags, created_at, updated_at}` with epoch-second timestamps.
`EntityType` = regulation | circular | amendment | institution | topic | requirement.
`NodeSource` includes manual, monitoring, ingestion, change_detection (plus
impact_analysis, research, user_upload). Frontend view (`adapters/knowledgeGraph.ts`):
`{id, label, type, description, tags}` with a malformed-payload fallback
(`label: "Untitled entity"`, non-string fields coerced, tags filtered to strings).

## 4. Relationship model
Backend `GraphRelationship`: `{relationship_id, source_id, target_id,
relationship_type, weight, confidence, properties, created_at}`.
`RelationshipType` = amends | references | supersedes | affects | relates_to.
Edges are DIRECTED (source → target); the UI always labels direction
("Outgoing"/"Incoming", arrow glyphs, SVG markers) and never implies otherwise.

## 5. Traversal models
- `ImpactTraversalResult`: `{start_node_id, steps, affected_node_ids: string[],
  total_paths, max_depth_reached, duration_ms}`. Steps are
  `{from_node_id, to_node_id, relationship_type, depth, weight, path}` — endpoint
  NAMES are not included; the page resolves names through fetched nodes and falls
  back to the raw id.
- `DependencyAnalysisResult`: `{root_node_id, upstream: GraphNode[],
  downstream: GraphNode[], cycles_detected: number, max_chain_length: number,
  duration_ms}`. Upstream/downstream are FULL NODES (no per-node depth); cycles are
  a COUNT, not paths — the UI says so explicitly instead of inventing paths.

## 6. Page composition (`src/pages/KnowledgeGraphPage.tsx`)
Three columns on `xl` (300px / 1fr / 340px), stacked below:
1. **Entities** — debounced (300ms) server `name_contains` search, server
   `entity_type` filter, prev/next paging (`page_size=50`, Next disabled on a short
   page since the service unwraps the envelope and drops `has_more`/`total`).
   Selection is local state; list selection does NOT push history (no spam).
2. **Relationship graph** — `src/components/kg/GraphView.tsx`, dependency-free SVG
   (no graph library): deterministic radial layout (center = selection, inner ring =
   direct neighbors, outer ring = reachable), zoom/pan/reset, keyboard-operable
   nodes (`role=button`, `aria-pressed`), ≤60 rendered nodes with an explicit cap
   badge. A legend repeats every color encoding as text.
3. **Inspector + analysis** — node detail (type/source/description/tags/epochs via
   `formatRelative`), directional relationship lists with a `rel_type` filter,
   downstream reachability (depth 1–10 input, steps with depth badges), upstream
   dependencies (upstream/downstream lists, cycle count, longest chain).

## 7. Selection + deep links
Selection precedence: explicit clicks > route param. `/knowledge-graph/:nodeId`
(App.tsx) seeds `selectedId` on mount/param change, so refresh and shared links
restore the inspector, graph center, and analyses. An unknown id surfaces the
inspector's error panel with retry. "Clear selection" returns to the guidance empty
state.

## 8. Query keys (`kgKeys`)
`stats`, `nodes(params)`, `node(id)`, `relationships(params)`, `impact(id, depth,
relType)`, `dependency(id, depth)` — param-bearing factories so filter/depth changes
refetch independently. Pre-existing `nodes()`/`impact(id)` key shapes were extended;
no other page consumes `kgKeys`.

## 9. Service changes (`services/api/knowledgeGraphApi.ts`)
- Kept Stage-02 array returns (`getGraphNodes`, `getGraphRelationships`) — the
  contract tests index `[0]`, so envelope returns would regress them. Filters are
  optional params (backward compatible).
- Added `getGraphNode`, `getRelationship` (single-entity fetches the old page lacked).
- `getGraphImpact(nodeId, {max_depth, rel_type})` unchanged; `getDependencyAnalysis`
  already existed and now has its `DependencyAnalysisResult` type (was missing).
- Did NOT add a node-relationships helper: no such backend route exists; the page
  issues two filtered `GET /relationships` queries instead.

## 10. Honesty rules enforced
- Totals ONLY from `/stats`; the list shows "Page N · M shown", never "of X".
- Impact empty state: "None reachable within N hops" + "Absence means none reachable
  in the stored graph, not no real-world effect."
- Dependency cycles: count reported with "the backend reports a count, not the cycle
  paths."
- Step/dependency names that cannot be resolved render as raw ids (with `title`).
- Relationship counts in the inspector header describe the FETCHED window
  (page_size=100), not the graph total.

## 11. Loading/error/empty states
Every panel (stats, list, inspector, edges, impact, dependency) has independent
pending (Skeleton), error (ErrorState + Retry), and empty (EmptyState) states —
one failing query never blanks the others. All live lists use `aria-live="polite"`.

## 12. Responsive strategy
`xl` 3-column grid → single column stack; graph `h-[300px]` → `lg:h-[420px]`;
entity/relationship/impact lists get `max-h-*` + internal scroll so the page never
grows unbounded. Verified at 390/768/1024/1440 (screenshots below).

## 13. Accessibility
Graph is supplementary: all nodes/edges/depths exist as adjacent text
(inspector, relationship lists, step lists). SVG has `role="img"` + summary label;
nodes are keyboard-operable buttons with `aria-pressed`; legend swatches are
`aria-hidden` with text labels; color never carries meaning alone (badges, depth
labels, direction arrows all have text).

## 14. Security
Node ids are path-encoded (`encodePathSegment`); search input travels as a query
param (no HTML injection surface — React escapes); no `dangerouslySetInnerHTML`;
no new auth surface (page sits behind the existing `Protect` guard).

## 15. Backend limitations (honest)
- No `total`/`has_more` on the frontend list (service unwraps the envelope) →
  prev/next with short-page heuristic, no "Page N of M".
- Relationship window capped at 100 per direction; graph render capped at 60 nodes
  with an explicit badge.
- Traversal steps carry no names; dependency results carry no per-node depth and no
  cycle paths.
- `snapshot` (full export) intentionally unused — unbounded payload.
- No mutation UI (create node/relationship endpoints exist but are out of scope).

## 16. Deferred features
"Page N of M" totals (needs envelope-preserving service + contract-test update),
snapshot export, relationship detail view, mutation UI, multi-select/compare,
server-side name search ranking, graph layout alternatives.

## 17. Verification
- `tsc --noEmit` clean; `eslint` clean; `vite build` clean
  (KnowledgeGraphPage chunk ~24KB / ~7KB gzip).
- Full suite: 17 files / 245 tests pass, including 15 new
  `src/test/knowledge-graph.test.tsx` tests (search/filter/pagination params,
  selection, directional edges, impact POST + depth, dependency rendering, SVG
  interaction, deep link, error + malformed states).
- Responsive screenshots: `landing/_review/ds9-knowledge-graph-390x844.png`,
  `ds9-knowledge-graph-768x1024.png`, `ds9-knowledge-graph-1024x768.png`,
  `ds9-knowledge-graph-1440x900.png` (captured against vite dev with
  intercepted backend-shaped fixtures; zero horizontal overflow at all widths).
