/**
 * Knowledge-graph contracts. Backend: app/api/v1/knowledge_graph.py +
 * app/schemas/knowledge_graph.py (extra="forbid"). Timestamps epoch SECONDS.
 *
 * Verified: nodes are {node_id, entity_type, name, ...} (NOT label/type);
 * edges are {relationship_id, source_id, target_id, relationship_type, ...}.
 * Impact is POST with optional query {max_depth, rel_type}; unknown node → 400.
 */
import type { PaginatedResponse } from "./common";

export type EntityType =
  | "regulation" | "circular" | "amendment"
  | "institution" | "topic" | "requirement";

export type RelationshipType =
  | "amends" | "references" | "supersedes" | "affects" | "relates_to";

export type NodeSource =
  | "manual" | "monitoring" | "ingestion" | "change_detection";

export interface GraphNode {
  node_id: string;
  entity_type: EntityType;
  name: string;
  description: string;
  external_id?: string | null;
  source: NodeSource;
  properties: Record<string, unknown>;
  tags: string[];
  created_at: number;
  updated_at: number;
}

export type PaginatedNodes = PaginatedResponse<GraphNode>;

export interface GraphRelationship {
  relationship_id: string;
  source_id: string;
  target_id: string;
  relationship_type: RelationshipType;
  weight: number;
  confidence: number;
  properties: Record<string, unknown>;
  created_at: number;
}

export type PaginatedRelationships = PaginatedResponse<GraphRelationship>;

export interface TraversalStep {
  from_node_id: string;
  to_node_id: string;
  relationship_type: RelationshipType;
  depth: number;
  weight: number;
  path: string[];
}

export interface ImpactTraversalResult {
  start_node_id: string;
  steps: TraversalStep[];
  affected_node_ids: string[];
  total_paths: number;
  max_depth_reached: number;
  duration_ms: number;
}

export type ImpactTraversalQuery = {
  max_depth?: number;
  rel_type?: RelationshipType;
}

export interface GraphStats {
  total_nodes: number;
  total_relationships: number;
  by_entity_type: Record<string, number>;
  by_relationship_type: Record<string, number>;
  by_source: Record<string, number>;
  average_degree: number;
  max_depth: number;
  connected_components: number;
  generated_at: number;
}
