"""Module 8.4 — Workflow Automation Platform contracts.

Pydantic v2 with ``extra="forbid"`` for all models. Designed to integrate
with Module 8.5 (Human-in-the-Loop Review) and Module 8.1-8.3
(Risk, Recommendations, Forecasting) via source references.
"""

from __future__ import annotations

import secrets
import time
import uuid
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


# ─── Enums ──────────────────────────────────────────────────────────


class WorkflowType(str, Enum):
    COMPLIANCE_REVIEW = "compliance_review"
    RISK_ASSESSMENT = "risk_assessment"
    POLICY_UPDATE = "policy_update"
    REGULATORY_CHANGE_REVIEW = "regulatory_change_review"


class WorkflowStatus(str, Enum):
    DRAFT = "draft"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    FAILED = "failed"


class StepType(str, Enum):
    TASK = "task"
    APPROVAL = "approval"
    REVIEW = "review"
    AUTOMATED = "automated"
    NOTIFICATION = "notification"


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"
    BLOCKED = "blocked"
    FAILED = "failed"


class TaskPriority(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    URGENT = "urgent"


class EscalationTrigger(str, Enum):
    TIMEOUT = "timeout"
    REJECTION = "rejection"
    MANUAL = "manual"
    PRIORITY = "priority"
    FAILURE = "failure"


class EscalationAction(str, Enum):
    ESCALATE = "escalate"
    NOTIFY = "notify"
    AUTO_APPROVE = "auto_approve"
    AUTO_REJECT = "auto_reject"
    REASSIGN = "reassign"


# ─── Audit entry ───────────────────────────────────────────────────


class AuditEntry(BaseModel):
    """A single timestamped action in a workflow/review audit trail."""

    model_config = ConfigDict(extra="forbid")

    audit_id: str = Field(
        default_factory=lambda: f"aud-{secrets.token_hex(6)}"
    )
    action: str
    actor: str
    timestamp: float = Field(default_factory=time.time)
    details: Dict[str, Any] = Field(default_factory=dict)
    source: str = "workflow_engine"


# ─── Workflow building blocks ──────────────────────────────────────


class WorkflowStep(BaseModel):
    """A single step in a workflow definition."""

    model_config = ConfigDict(extra="forbid")

    step_id: str = Field(
        default_factory=lambda: f"stp-{secrets.token_hex(4)}"
    )
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    step_type: StepType = StepType.TASK
    sequence: int = 0
    depends_on: List[str] = Field(default_factory=list)
    timeout_hours: int = Field(24, ge=1, le=8760)
    assignee: str = ""
    assignee_role: str = ""
    requires_approval: bool = False
    config: Dict[str, Any] = Field(default_factory=dict)


class TaskAssignment(BaseModel):
    """A concrete task instance assigned during workflow execution."""

    model_config = ConfigDict(extra="forbid")

    task_id: str = Field(
        default_factory=lambda: f"tsk-{secrets.token_hex(4)}"
    )
    workflow_id: str
    step_id: str
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    assignee: str = ""
    assignee_role: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    status: TaskStatus = TaskStatus.PENDING
    created_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    due_at: Optional[float] = None
    result: Dict[str, Any] = Field(default_factory=dict)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EscalationRule(BaseModel):
    """Rule that triggers a workflow escalation."""

    model_config = ConfigDict(extra="forbid")

    rule_id: str = Field(
        default_factory=lambda: f"esc-{secrets.token_hex(4)}"
    )
    trigger: EscalationTrigger
    threshold_hours: int = Field(24, ge=0, le=8760)
    action: EscalationAction = EscalationAction.ESCALATE
    target: str = ""
    priority: int = Field(1, ge=1, le=10)
    enabled: bool = True
    notes: str = ""


# ─── Workflow ──────────────────────────────────────────────────────


class Workflow(BaseModel):
    """A workflow instance with definition, tasks, and audit trail."""

    model_config = ConfigDict(extra="forbid")

    workflow_id: str = Field(
        default_factory=lambda: f"wf-{uuid.uuid4().hex[:12]}"
    )
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    workflow_type: WorkflowType
    status: WorkflowStatus = WorkflowStatus.DRAFT
    document_id: Optional[str] = None
    source_recommendation_id: Optional[str] = None
    source_risk_assessment_id: Optional[str] = None
    steps: List[WorkflowStep] = Field(default_factory=list)
    tasks: List[TaskAssignment] = Field(default_factory=list)
    escalation_rules: List[EscalationRule] = Field(default_factory=list)
    current_step_index: int = 0
    created_at: float = Field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None
    created_by: str = "system"
    priority: TaskPriority = TaskPriority.MEDIUM
    metadata: Dict[str, Any] = Field(default_factory=dict)
    audit_trail: List[AuditEntry] = Field(default_factory=list)


# ─── Requests / Filters / Stats ────────────────────────────────────


class WorkflowCreateRequest(BaseModel):
    """Request to create a new workflow instance."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    workflow_type: WorkflowType
    steps: List[WorkflowStep] = Field(default_factory=list)
    document_id: Optional[str] = None
    source_recommendation_id: Optional[str] = None
    source_risk_assessment_id: Optional[str] = None
    created_by: str = "system"
    priority: TaskPriority = TaskPriority.MEDIUM
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskCreateRequest(BaseModel):
    """Request to add a task to a running workflow."""

    model_config = ConfigDict(extra="forbid")

    step_id: str
    title: str = Field(..., min_length=1, max_length=300)
    description: str = ""
    assignee: str = ""
    assignee_role: str = ""
    priority: TaskPriority = TaskPriority.MEDIUM
    due_at: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class TaskCompletionRequest(BaseModel):
    """Request to mark a task complete."""

    model_config = ConfigDict(extra="forbid")

    status: TaskStatus = TaskStatus.COMPLETED
    result: Dict[str, Any] = Field(default_factory=dict)
    notes: str = ""


class TaskAssignmentRequest(BaseModel):
    """Request to (re)assign a task."""

    model_config = ConfigDict(extra="forbid")

    assignee: str
    assignee_role: str = ""


class EscalationRequest(BaseModel):
    """Request to manually escalate a workflow."""

    model_config = ConfigDict(extra="forbid")

    rule_id: Optional[str] = None
    reason: str = ""
    target: str = ""


class WorkflowFilter(BaseModel):
    """Query filter for workflows."""

    model_config = ConfigDict(extra="forbid")

    workflow_type: Optional[WorkflowType] = None
    status: Optional[WorkflowStatus] = None
    document_id: Optional[str] = None
    created_by: Optional[str] = None
    after: Optional[float] = None
    before: Optional[float] = None
    page: int = Field(1, ge=1)
    page_size: int = Field(50, ge=1, le=200)


class PaginatedWorkflows(BaseModel):
    """Page of workflows."""

    model_config = ConfigDict(extra="forbid")

    items: List[Workflow] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 50
    has_more: bool = False


class WorkflowStats(BaseModel):
    """Aggregated workflow statistics."""

    model_config = ConfigDict(extra="forbid")

    total_workflows: int = 0
    by_status: Dict[str, int] = Field(default_factory=dict)
    by_type: Dict[str, int] = Field(default_factory=dict)
    total_tasks: int = 0
    tasks_by_status: Dict[str, int] = Field(default_factory=dict)
    success_rate: float = 0.0
    average_completion_seconds: float = 0.0
    escalations_triggered: int = 0
    last_workflow_at: Optional[float] = None


__all__ = [
    "WorkflowType",
    "WorkflowStatus",
    "StepType",
    "TaskStatus",
    "TaskPriority",
    "EscalationTrigger",
    "EscalationAction",
    "AuditEntry",
    "WorkflowStep",
    "TaskAssignment",
    "EscalationRule",
    "Workflow",
    "WorkflowCreateRequest",
    "TaskCreateRequest",
    "TaskCompletionRequest",
    "TaskAssignmentRequest",
    "EscalationRequest",
    "WorkflowFilter",
    "PaginatedWorkflows",
    "WorkflowStats",
]
