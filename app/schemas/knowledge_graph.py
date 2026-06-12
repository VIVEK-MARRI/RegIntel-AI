"""Module 7.6 — Knowledge Graph Layer schemas."""

from __future__ import annotations

import secrets
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ─── Enums ────────────────────────────────────────────────────────────


class EntityType(str, Enum):
    REGULATION = "regulation"
    CIRCULAR = "circular"
    AMENDMENT = "amendment"
    INSTITUTION = "institution"
    TOPIC = "topic"
    REQUIREMENT = "requirement"


class RelationshipType(str, Enum):
    AMENDS = "amends"
    REFERENCES = "references"
    SUPERSEDES = "supersedes"
    AFFECTS = "affects"
    RELATES_TO = "relates_to"


class NodeSource(str, Enum):
    """Where a graph node came from."""

    MANUAL = "manual"
    MONITORING = "monitoring"
    INGESTION = "ingestion"
    CHANGE_DETECTION = "change_detection"
    IMPACT_ANALYSIS = "impact_analysis"
    RESEARCH = "research"
    USER_UPLOAD = "user_upload"


# ─── Graph nodes ────────────────────────────────────────────────────


class GraphNode(BaseModel):
    """A node in the regulatory knowledge graph."""

    model_config = ConfigDict(extra="forbid")

    node_id: str = Field(default_factory=lambda: f"node-{secrets.token_hex(6)}")
    entity_type: EntityType
    name: str = Field(..., min_length=1, max_length=300)
    description: str = Field("", max_length=4000)
    external_id: Optional[str] = None
    source: NodeSource = NodeSource.MANUAL
    properties: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)
    created_at: float = 0.0
    updated_at: float = 0.0

    @field_validator("name")
    @classmethod
    def _strip_name(cls, v: str) -> str:
        return v.strip()


class GraphRelationship(BaseModel):
    """A directed edge between two nodes."""

    model_config = ConfigDict(extra="forbid")

    relationship_id: str = Field(
        default_factory=lambda: f"rel-{secrets.token_hex(6)}"
    )
    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    relationship_type: RelationshipType
    weight: float = Field(1.0, ge=0.0, le=10.0)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    properties: Dict[str, Any] = Field(default_factory=dict)
    created_at: float = 0.0

    @field_validator("source_id", "target_id")
    @classmethod
    def _not_same(cls, v: str, info) -> str:  # type: ignore[no-untyped-def]
        return v


# ─── Requests / Responses ─────────────────────────────────────────────


class NodeCreateRequest(BaseModel):
    """Create a new graph node."""

    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    name: str = Field(..., min_length=1, max_length=300)
    description: str = Field("", max_length=4000)
    external_id: Optional[str] = None
    source: NodeSource = NodeSource.MANUAL
    properties: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)


class RelationshipCreateRequest(BaseModel):
    """Create a new edge between two nodes."""

    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(..., min_length=1)
    target_id: str = Field(..., min_length=1)
    relationship_type: RelationshipType
    weight: float = Field(1.0, ge=0.0, le=10.0)
    confidence: float = Field(1.0, ge=0.0, le=1.0)
    properties: Dict[str, Any] = Field(default_factory=dict)


class NodeFilter(BaseModel):
    """Query filter for nodes."""

    model_config = ConfigDict(extra="forbid")

    entity_type: Optional[EntityType] = None
    source: Optional[NodeSource] = None
    name_contains: Optional[str] = None
    tag: Optional[str] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=500)


class PaginatedNodes(BaseModel):
    """Page of nodes."""

    model_config = ConfigDict(extra="forbid")

    items: List[GraphNode] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class PaginatedRelationships(BaseModel):
    """Page of relationships."""

    model_config = ConfigDict(extra="forbid")

    items: List[GraphRelationship] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


# ─── Graph analysis outputs ──────────────────────────────────────────


class TraversalStep(BaseModel):
    """A single hop in a graph traversal."""

    model_config = ConfigDict(extra="forbid")

    from_node_id: str
    to_node_id: str
    relationship_type: RelationshipType
    depth: int
    weight: float = 1.0
    path: List[str] = Field(default_factory=list)


class ImpactTraversalResult(BaseModel):
    """Output of an impact traversal query."""

    model_config = ConfigDict(extra="forbid")

    start_node_id: str
    steps: List[TraversalStep] = Field(default_factory=list)
    affected_node_ids: List[str] = Field(default_factory=list)
    total_paths: int = 0
    max_depth_reached: int = 0
    duration_ms: float = 0.0


class DependencyAnalysisResult(BaseModel):
    """Output of a dependency analysis query."""

    model_config = ConfigDict(extra="forbid")

    root_node_id: str
    upstream: List[GraphNode] = Field(default_factory=list)
    downstream: List[GraphNode] = Field(default_factory=list)
    cycles_detected: int = 0
    max_chain_length: int = 0
    duration_ms: float = 0.0


class GraphStats(BaseModel):
    """Aggregate graph statistics."""

    model_config = ConfigDict(extra="forbid")

    total_nodes: int = 0
    total_relationships: int = 0
    by_entity_type: Dict[str, int] = Field(default_factory=dict)
    by_relationship_type: Dict[str, int] = Field(default_factory=dict)
    by_source: Dict[str, int] = Field(default_factory=dict)
    average_degree: float = 0.0
    max_depth: int = 0
    connected_components: int = 0
    generated_at: float = 0.0


class GraphSnapshot(BaseModel):
    """Full export of a graph (or subgraph)."""

    model_config = ConfigDict(extra="forbid")

    nodes: List[GraphNode] = Field(default_factory=list)
    relationships: List[GraphRelationship] = Field(default_factory=list)
    stats: GraphStats
    generated_at: float = 0.0


__all__ = [
    "EntityType",
    "RelationshipType",
    "NodeSource",
    "GraphNode",
    "GraphRelationship",
    "NodeCreateRequest",
    "RelationshipCreateRequest",
    "NodeFilter",
    "PaginatedNodes",
    "PaginatedRelationships",
    "TraversalStep",
    "ImpactTraversalResult",
    "DependencyAnalysisResult",
    "GraphStats",
    "GraphSnapshot",
]
