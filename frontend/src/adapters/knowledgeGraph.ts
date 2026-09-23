/** Knowledge-graph view models: backend names → display names. */
import type { GraphNode, GraphRelationship } from "@/types/api/knowledgeGraph";

export interface GraphNodeView {
  id: string;
  label: string;
  type: string;
  description: string;
  tags: string[];
}

export function toNodeView(n: GraphNode): GraphNodeView {
  return {
    id: typeof n.node_id === "string" ? n.node_id : String(n.node_id ?? ""),
    label: typeof n.name === "string" && n.name ? n.name : "Untitled entity",
    type: typeof n.entity_type === "string" ? n.entity_type : "unknown",
    description: typeof n.description === "string" ? n.description : "",
    tags: Array.isArray(n.tags) ? n.tags.filter((t): t is string => typeof t === "string") : [],
  };
}

export interface GraphEdgeView {
  id: string;
  source: string;
  target: string;
  type: string;
  weight: number;
}

export function toEdgeView(e: GraphRelationship): GraphEdgeView {
  return {
    id: e.relationship_id,
    source: e.source_id,
    target: e.target_id,
    type: e.relationship_type,
    weight: e.weight,
  };
}
