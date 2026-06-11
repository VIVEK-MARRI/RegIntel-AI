import { api } from "@/lib/api";
import type { GraphNode, GraphRelationship, KnowledgeGraphStats } from "@/types";

export async function getGraphStats(): Promise<KnowledgeGraphStats> {
  return api.get<KnowledgeGraphStats>("/knowledge-graph/stats");
}

export async function getGraphNodes(): Promise<GraphNode[]> {
  return api.get<GraphNode[]>("/knowledge-graph/nodes");
}

export async function getGraphRelationships(): Promise<GraphRelationship[]> {
  return api.get<GraphRelationship[]>("/knowledge-graph/relationships");
}

export async function getGraphImpact(nodeId: string): Promise<{ affected: GraphNode[]; total: number }> {
  return api.get<{ affected: GraphNode[]; total: number }>(`/knowledge-graph/impact-traversal/${nodeId}`);
}
