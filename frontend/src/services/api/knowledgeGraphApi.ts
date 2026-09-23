import { api, encodePathSegment } from "@/lib/api";
import type {
  DependencyAnalysisResult,
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

export async function getGraphNode(nodeId: string): Promise<GraphNode> {
  return api.get<GraphNode>(`/knowledge-graph/nodes/${encodePathSegment(nodeId)}`);
}

export type GraphRelationshipsQuery = {
  source_id?: string;
  target_id?: string;
  rel_type?: string;
  page?: number;
  page_size?: number;
}

export async function getGraphRelationships(
  query?: GraphRelationshipsQuery
): Promise<GraphRelationship[]> {
  const res = await api.get<PaginatedRelationships>("/knowledge-graph/relationships", { query });
  return res.items ?? [];
}

export async function getRelationship(relId: string): Promise<GraphRelationship> {
  return api.get<GraphRelationship>(
    `/knowledge-graph/relationships/${encodePathSegment(relId)}`
  );
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

export async function getDependencyAnalysis(
  nodeId: string,
  maxDepth?: number
): Promise<DependencyAnalysisResult> {
  return api.post<DependencyAnalysisResult>(
    `/knowledge-graph/dependency-analysis/${encodePathSegment(nodeId)}`,
    undefined,
    { query: maxDepth != null ? { max_depth: maxDepth } : undefined }
  );
}
