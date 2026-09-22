import { api, encodePathSegment } from "@/lib/api";
import type {
  GraphNode,
  GraphRelationship,
  GraphStats,
  ImpactTraversalQuery,
  ImpactTraversalResult,
  PaginatedNodes,
  PaginatedRelationships,
} from "@/types/api/knowledgeGraph";

export async function getGraphStats(): Promise<GraphStats> {
  return api.get<GraphStats>("/knowledge-graph/stats");
}

export type GraphNodesQuery = {
  entity_type?: string;
  source?: string;
  name_contains?: string;
  tag?: string;
  page?: number;
  page_size?: number;
}

export async function getGraphNodes(
  query?: GraphNodesQuery
): Promise<GraphNode[]> {
  const res = await api.get<PaginatedNodes>("/knowledge-graph/nodes", { query });
  return res.items;
}

export async function getGraphRelationships(): Promise<GraphRelationship[]> {
  const res = await api.get<PaginatedRelationships>("/knowledge-graph/relationships");
  return res.items ?? [];
}

export async function getGraphImpact(
  nodeId: string,
  query?: ImpactTraversalQuery
): Promise<ImpactTraversalResult> {
  return api.post<ImpactTraversalResult>(
    `/knowledge-graph/impact-traversal/${encodePathSegment(nodeId)}`,
    undefined,
    { query }
  );
}
