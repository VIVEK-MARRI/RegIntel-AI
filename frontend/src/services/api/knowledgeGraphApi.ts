import { api } from "@/lib/api";
import type { GraphNode, GraphRelationship, KnowledgeGraphStats } from "@/types";

export async function getGraphStats(): Promise<KnowledgeGraphStats> {
  return api.get<KnowledgeGraphStats>("/knowledge-graph/stats");
}

export async function getGraphNodes(): Promise<GraphNode[]> {
  return api.get<{ items: GraphNode[] }>("/knowledge-graph/nodes").then((r) => r.items);
}

export async function getGraphRelationships(): Promise<GraphRelationship[]> {
  return api
    .get<{ items: GraphRelationship[] }>("/knowledge-graph/relationships")
    .then((r) => r.items ?? []);
}

export interface GraphImpact {
  start_node_id: string;
  affected_node_ids: string[];
  total_paths: number;
  max_depth_reached: number;
  steps: unknown[];
}

export async function getGraphImpact(nodeId: string): Promise<GraphImpact> {
  return api.post<GraphImpact>(`/knowledge-graph/impact-traversal/${nodeId}`);
}
