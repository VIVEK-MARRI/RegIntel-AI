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
    id: n.node_id,
    label: n.name,
    type: n.entity_type,
    description: n.description,
    tags: n.tags,
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
