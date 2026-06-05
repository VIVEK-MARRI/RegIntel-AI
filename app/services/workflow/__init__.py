"""Module 8.4 — Workflow Automation Platform.

Public surface
--------------
* ``WorkflowEngine``            — state machine for individual workflows
* ``TaskManager``               — task assignment, completion, tracking
* ``WorkflowOrchestrator``      — inter-workflow routing and progression
* ``WorkflowRepository``        — search / stats / audit
* ``WorkflowStore`` (ABC) + ``InMemoryWorkflowStore``
* ``AutomationService``         — DI facade
* ``build_default_automation_service``
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.config import settings
from app.schemas.workflow import (
    AuditEntry,
    EscalationAction,
    EscalationRequest,
    EscalationRule,
    EscalationTrigger,
    PaginatedWorkflows,
    StepType,
    TaskAssignment,
    TaskAssignmentRequest,
    TaskCompletionRequest,
    TaskCreateRequest,
    TaskPriority,
    TaskStatus,
    Workflow,
    WorkflowCreateRequest,
    WorkflowFilter,
    WorkflowStats,
    WorkflowStatus,
    WorkflowStep,
    WorkflowType,
)
from app.services.observability import (
    get_workflow_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── Default templates per workflow type ───────────────────────────


_DEFAULT_TEMPLATES: Dict[WorkflowType, List[WorkflowStep]] = {
    WorkflowType.COMPLIANCE_REVIEW: [
        WorkflowStep(
            name="Initial compliance review",
            description="Compliance officer reviews the change",
            step_type=StepType.REVIEW,
            sequence=1,
            timeout_hours=24,
            assignee_role="compliance_officer",
            requires_approval=True,
        ),
        WorkflowStep(
            name="Risk validation",
            description="Risk team validates the impact",
            step_type=StepType.APPROVAL,
            sequence=2,
            depends_on=["1"],
            timeout_hours=24,
            assignee_role="risk_manager",
            requires_approval=True,
        ),
        WorkflowStep(
            name="Policy update",
            description="Update internal policy and circulate",
            step_type=StepType.TASK,
            sequence=3,
            depends_on=["2"],
            timeout_hours=48,
            assignee_role="policy_lead",
        ),
        WorkflowStep(
            name="Sign-off and close",
            description="Final sign-off by compliance head",
            step_type=StepType.APPROVAL,
            sequence=4,
            depends_on=["3"],
            timeout_hours=24,
            assignee_role="compliance_head",
            requires_approval=True,
        ),
    ],
    WorkflowType.RISK_ASSESSMENT: [
        WorkflowStep(
            name="Risk identification",
            description="Identify all impacted areas",
            step_type=StepType.TASK,
            sequence=1,
            timeout_hours=12,
            assignee_role="risk_analyst",
        ),
        WorkflowStep(
            name="Risk scoring",
            description="Compute composite risk score",
            step_type=StepType.AUTOMATED,
            sequence=2,
            depends_on=["1"],
            timeout_hours=4,
        ),
        WorkflowStep(
            name="Risk review",
            description="Risk manager review of the assessment",
            step_type=StepType.REVIEW,
            sequence=3,
            depends_on=["2"],
            timeout_hours=24,
            assignee_role="risk_manager",
            requires_approval=True,
        ),
    ],
    WorkflowType.POLICY_UPDATE: [
        WorkflowStep(
            name="Draft policy",
            description="Author the updated policy",
            step_type=StepType.TASK,
            sequence=1,
            timeout_hours=48,
            assignee_role="policy_lead",
        ),
        WorkflowStep(
            name="Legal review",
            description="Legal team reviews the draft",
            step_type=StepType.REVIEW,
            sequence=2,
            depends_on=["1"],
            timeout_hours=24,
            assignee_role="legal_counsel",
            requires_approval=True,
        ),
        WorkflowStep(
            name="Compliance review",
            description="Compliance team reviews the draft",
            step_type=StepType.REVIEW,
            sequence=3,
            depends_on=["2"],
            timeout_hours=24,
            assignee_role="compliance_officer",
            requires_approval=True,
        ),
        WorkflowStep(
            name="Approval and publish",
            description="Final approval and publish",
            step_type=StepType.APPROVAL,
            sequence=4,
            depends_on=["3"],
            timeout_hours=24,
            assignee_role="chief_compliance_officer",
            requires_approval=True,
        ),
    ],
    WorkflowType.REGULATORY_CHANGE_REVIEW: [
        WorkflowStep(
            name="Change analysis",
            description="Analyse the regulatory change",
            step_type=StepType.AUTOMATED,
            sequence=1,
            timeout_hours=2,
        ),
        WorkflowStep(
            name="Impact assessment",
            description="Quantify the impact",
            step_type=StepType.TASK,
            sequence=2,
            depends_on=["1"],
            timeout_hours=24,
            assignee_role="risk_analyst",
        ),
        WorkflowStep(
            name="Stakeholder review",
            description="Stakeholder review meeting",
            step_type=StepType.REVIEW,
            sequence=3,
            depends_on=["2"],
            timeout_hours=48,
            assignee_role="business_lead",
            requires_approval=True,
        ),
        WorkflowStep(
            name="Implementation plan",
            description="Define implementation plan",
            step_type=StepType.TASK,
            sequence=4,
            depends_on=["3"],
            timeout_hours=72,
            assignee_role="project_lead",
        ),
    ],
}


_DEFAULT_ESCALATION_RULES: List[EscalationRule] = [
    EscalationRule(
        trigger=EscalationTrigger.TIMEOUT,
        threshold_hours=48,
        action=EscalationAction.ESCALATE,
        target="compliance_head",
        priority=1,
    ),
    EscalationRule(
        trigger=EscalationTrigger.REJECTION,
        threshold_hours=0,
        action=EscalationAction.ESCALATE,
        target="compliance_head",
        priority=2,
    ),
    EscalationRule(
        trigger=EscalationTrigger.MANUAL,
        threshold_hours=0,
        action=EscalationAction.NOTIFY,
        target="compliance_team",
        priority=3,
    ),
]


# ─── WorkflowEngine ────────────────────────────────────────────────


class WorkflowEngine:
    """State machine for workflow lifecycle and progression."""

    _TERMINAL_STATUSES: set = {
        WorkflowStatus.COMPLETED,
        WorkflowStatus.CANCELLED,
        WorkflowStatus.FAILED,
    }

    def create(
        self, request: WorkflowCreateRequest
    ) -> Workflow:
        with track_request(
            endpoint="/api/v1/workflow/create",
            strategy="workflow_create",
        ):
            steps = (
                list(request.steps)
                if request.steps
                else list(
                    _DEFAULT_TEMPLATES.get(request.workflow_type, [])
                )
            )
            wf = Workflow(
                name=request.name,
                description=request.description,
                workflow_type=request.workflow_type,
                document_id=request.document_id,
                source_recommendation_id=request.source_recommendation_id,
                source_risk_assessment_id=request.source_risk_assessment_id,
                steps=steps,
                escalation_rules=list(_DEFAULT_ESCALATION_RULES),
                created_by=request.created_by,
                priority=request.priority,
                metadata=request.metadata,
                status=WorkflowStatus.DRAFT
                if not steps
                else WorkflowStatus.ACTIVE,
                audit_trail=[
                    AuditEntry(
                        action="workflow.created",
                        actor=request.created_by,
                        details={
                            "workflow_type": request.workflow_type.value,
                            "step_count": len(steps),
                        },
                    )
                ],
            )
            get_workflow_metrics().record_created(request.workflow_type.value)
            return wf

    def start(self, wf: Workflow, actor: str = "system") -> Workflow:
        if wf.status not in (
            WorkflowStatus.DRAFT,
            WorkflowStatus.PAUSED,
            WorkflowStatus.ACTIVE,
        ):
            raise ValueError(
                f"Cannot start workflow in status {wf.status.value}"
            )
        if wf.status == WorkflowStatus.ACTIVE and wf.started_at is not None:
            # Already running; idempotent
            return wf
        wf.status = WorkflowStatus.ACTIVE
        wf.started_at = wf.started_at or time.time()
        wf.audit_trail.append(
            AuditEntry(
                action="workflow.started",
                actor=actor,
                details={"step_index": wf.current_step_index},
            )
        )
        get_workflow_metrics().record_started()
        return wf

    def pause(self, wf: Workflow, actor: str = "system") -> Workflow:
        if wf.status != WorkflowStatus.ACTIVE:
            raise ValueError(
                f"Cannot pause workflow in status {wf.status.value}"
            )
        wf.status = WorkflowStatus.PAUSED
        wf.audit_trail.append(
            AuditEntry(action="workflow.paused", actor=actor)
        )
        return wf

    def resume(self, wf: Workflow, actor: str = "system") -> Workflow:
        if wf.status != WorkflowStatus.PAUSED:
            raise ValueError(
                f"Cannot resume workflow in status {wf.status.value}"
            )
        wf.status = WorkflowStatus.ACTIVE
        wf.audit_trail.append(
            AuditEntry(action="workflow.resumed", actor=actor)
        )
        return wf

    def cancel(
        self, wf: Workflow, actor: str = "system", reason: str = ""
    ) -> Workflow:
        if wf.status in self._TERMINAL_STATUSES:
            raise ValueError(
                f"Cannot cancel workflow in terminal status {wf.status.value}"
            )
        wf.status = WorkflowStatus.CANCELLED
        wf.completed_at = time.time()
        wf.audit_trail.append(
            AuditEntry(
                action="workflow.cancelled",
                actor=actor,
                details={"reason": reason},
            )
        )
        get_workflow_metrics().record_cancelled()
        return wf

    def complete(self, wf: Workflow, actor: str = "system") -> Workflow:
        if wf.status != WorkflowStatus.ACTIVE:
            raise ValueError(
                f"Cannot complete workflow in status {wf.status.value}"
            )
        # Ensure all tasks are completed
        pending = [
            t for t in wf.tasks
            if t.status not in (TaskStatus.COMPLETED, TaskStatus.SKIPPED)
        ]
        if pending:
            raise ValueError(
                f"Cannot complete: {len(pending)} task(s) still pending"
            )
        wf.status = WorkflowStatus.COMPLETED
        wf.completed_at = time.time()
        wf.audit_trail.append(
            AuditEntry(
                action="workflow.completed",
                actor=actor,
                details={"total_tasks": len(wf.tasks)},
            )
        )
        get_workflow_metrics().record_completed()
        return wf

    def fail(
        self, wf: Workflow, actor: str = "system", reason: str = ""
    ) -> Workflow:
        wf.status = WorkflowStatus.FAILED
        wf.completed_at = time.time()
        wf.audit_trail.append(
            AuditEntry(
                action="workflow.failed",
                actor=actor,
                details={"reason": reason},
            )
        )
        get_workflow_metrics().record_failed()
        return wf

    def advance_step(self, wf: Workflow, actor: str = "system") -> Workflow:
        if not wf.steps:
            return wf
        if wf.current_step_index < len(wf.steps) - 1:
            wf.current_step_index += 1
            wf.audit_trail.append(
                AuditEntry(
                    action="workflow.step_advanced",
                    actor=actor,
                    details={"step_index": wf.current_step_index},
                )
            )
        return wf

    def is_terminal(self, wf: Workflow) -> bool:
        return wf.status in self._TERMINAL_STATUSES


# ─── TaskManager ──────────────────────────────────────────────────


class TaskManager:
    """Create, assign, complete, and track tasks within a workflow."""

    def add_task(
        self, wf: Workflow, request: TaskCreateRequest
    ) -> TaskAssignment:
        # Verify the step exists
        step = next(
            (s for s in wf.steps if s.step_id == request.step_id), None
        )
        if step is None:
            raise ValueError(
                f"Step {request.step_id} not found in workflow {wf.workflow_id}"
            )
        task = TaskAssignment(
            workflow_id=wf.workflow_id,
            step_id=request.step_id,
            title=request.title,
            description=request.description,
            assignee=request.assignee or step.assignee,
            assignee_role=request.assignee_role or step.assignee_role,
            priority=request.priority,
            due_at=request.due_at,
            metadata=request.metadata,
        )
        wf.tasks.append(task)
        wf.audit_trail.append(
            AuditEntry(
                action="task.created",
                actor=wf.created_by,
                details={
                    "task_id": task.task_id,
                    "step_id": task.step_id,
                },
            )
        )
        get_workflow_metrics().record_task_created()
        return task

    def assign(
        self,
        wf: Workflow,
        task_id: str,
        request: TaskAssignmentRequest,
        actor: str = "system",
    ) -> TaskAssignment:
        task = self._find_task(wf, task_id)
        task.assignee = request.assignee
        if request.assignee_role:
            task.assignee_role = request.assignee_role
        wf.audit_trail.append(
            AuditEntry(
                action="task.assigned",
                actor=actor,
                details={
                    "task_id": task.task_id,
                    "assignee": request.assignee,
                },
            )
        )
        return task

    def start_task(
        self, wf: Workflow, task_id: str, actor: str = "system"
    ) -> TaskAssignment:
        task = self._find_task(wf, task_id)
        if task.status not in (TaskStatus.PENDING, TaskStatus.BLOCKED):
            raise ValueError(
                f"Cannot start task in status {task.status.value}"
            )
        task.status = TaskStatus.IN_PROGRESS
        task.started_at = time.time()
        wf.audit_trail.append(
            AuditEntry(
                action="task.started",
                actor=actor,
                details={"task_id": task.task_id},
            )
        )
        return task

    def complete_task(
        self,
        wf: Workflow,
        task_id: str,
        request: TaskCompletionRequest,
        actor: str = "system",
    ) -> TaskAssignment:
        task = self._find_task(wf, task_id)
        if task.status in (TaskStatus.COMPLETED, TaskStatus.SKIPPED):
            raise ValueError(
                f"Task {task_id} already in terminal status {task.status.value}"
            )
        task.status = request.status
        task.completed_at = time.time()
        task.result = {**task.result, **request.result}
        if request.notes:
            task.result["notes"] = request.notes
        wf.audit_trail.append(
            AuditEntry(
                action="task.completed",
                actor=actor,
                details={
                    "task_id": task.task_id,
                    "status": request.status.value,
                },
            )
        )
        get_workflow_metrics().record_task_completed(
            status=request.status.value
        )
        return task

    def tasks_for_assignee(
        self, wf: Workflow, assignee: str
    ) -> List[TaskAssignment]:
        return [t for t in wf.tasks if t.assignee == assignee]

    def tasks_by_status(
        self, wf: Workflow, status: TaskStatus
    ) -> List[TaskAssignment]:
        return [t for t in wf.tasks if t.status == status]

    @staticmethod
    def _find_task(wf: Workflow, task_id: str) -> TaskAssignment:
        task = next(
            (t for t in wf.tasks if t.task_id == task_id), None
        )
        if task is None:
            raise ValueError(
                f"Task {task_id} not found in workflow {wf.workflow_id}"
            )
        return task


# ─── WorkflowOrchestrator ──────────────────────────────────────────


class WorkflowOrchestrator:
    """Cross-workflow progression, escalation, and routing."""

    def __init__(self) -> None:
        self._escalations = 0

    @property
    def escalations(self) -> int:
        return self._escalations

    def trigger_escalation(
        self, wf: Workflow, request: EscalationRequest, actor: str = "system"
    ) -> EscalationRule:
        # Pick a matching rule (manual request or first matching one)
        rule: Optional[EscalationRule] = None
        if request.rule_id:
            rule = next(
                (
                    r
                    for r in wf.escalation_rules
                    if r.rule_id == request.rule_id and r.enabled
                ),
                None,
            )
        if rule is None:
            # Prefer an ESCALATE action (any trigger) so the
            # workflow actually escalates by default
            rule = next(
                (
                    r
                    for r in wf.escalation_rules
                    if r.action == EscalationAction.ESCALATE
                    and r.enabled
                ),
                None,
            )
        if rule is None:
            rule = next(
                (
                    r
                    for r in wf.escalation_rules
                    if r.trigger
                    in (
                        EscalationTrigger.MANUAL,
                        EscalationTrigger.FAILURE,
                    )
                    and r.enabled
                ),
                wf.escalation_rules[0] if wf.escalation_rules else None,
            )
        if rule is None:
            raise ValueError("No escalation rule available")
        wf.audit_trail.append(
            AuditEntry(
                action="workflow.escalated",
                actor=actor,
                details={
                    "rule_id": rule.rule_id,
                    "trigger": rule.trigger.value,
                    "action": rule.action.value,
                    "target": request.target or rule.target,
                    "reason": request.reason,
                },
            )
        )
        self._escalations += 1
        get_workflow_metrics().record_escalation(rule.action.value)
        return rule

    def evaluate_timeouts(self, wf: Workflow) -> List[EscalationRule]:
        """Walk rules and return any triggered by elapsed time."""
        if wf.started_at is None:
            return []
        elapsed_h = (time.time() - wf.started_at) / 3600.0
        triggered: List[EscalationRule] = []
        for rule in wf.escalation_rules:
            if not rule.enabled:
                continue
            if (
                rule.trigger == EscalationTrigger.TIMEOUT
                and elapsed_h >= rule.threshold_hours
            ):
                triggered.append(rule)
        return triggered

    def route(self, wf: Workflow) -> Optional[WorkflowStep]:
        """Return the step the workflow is currently on (or None)."""
        if not wf.steps:
            return None
        if 0 <= wf.current_step_index < len(wf.steps):
            return wf.steps[wf.current_step_index]
        return None

    def progress_percent(self, wf: Workflow) -> float:
        if not wf.steps:
            return 0.0
        if wf.status == WorkflowStatus.COMPLETED:
            return 100.0
        return round(
            wf.current_step_index / max(1, len(wf.steps) - 1) * 100.0, 2
        )


# ─── Store ─────────────────────────────────────────────────────────


class WorkflowStore(ABC):
    @abstractmethod
    def add(self, wf: Workflow) -> None: ...

    @abstractmethod
    def get(self, workflow_id: str) -> Optional[Workflow]: ...

    @abstractmethod
    def list_all(self) -> List[Workflow]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryWorkflowStore(WorkflowStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._items: Dict[str, Workflow] = {}
        self._persist_path = persist_path
        if self._persist_path and os.path.exists(self._persist_path):
            self._load()

    def _load(self) -> None:
        try:
            with open(self._persist_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                        wf = Workflow(**data)
                        self._items[wf.workflow_id] = wf
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, wf: Workflow) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(wf.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add(self, wf: Workflow) -> None:
        with self._lock:
            self._items[wf.workflow_id] = wf
        self._persist(wf)

    def get(self, workflow_id: str) -> Optional[Workflow]:
        with self._lock:
            return self._items.get(workflow_id)

    def list_all(self) -> List[Workflow]:
        with self._lock:
            return list(self._items.values())

    def reset(self) -> None:
        with self._lock:
            self._items.clear()
        if self._persist_path and os.path.exists(self._persist_path):
            try:
                os.remove(self._persist_path)
            except Exception:  # pragma: no cover
                pass


# ─── Repository ────────────────────────────────────────────────────


class WorkflowRepository:
    def __init__(self, store: WorkflowStore) -> None:
        self._store = store

    def add(self, wf: Workflow) -> None:
        self._store.add(wf)

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self._store.get(workflow_id)

    def search(self, flt: WorkflowFilter) -> PaginatedWorkflows:
        items = self._store.list_all()
        if flt.workflow_type:
            items = [
                w for w in items
                if w.workflow_type == flt.workflow_type
            ]
        if flt.status:
            items = [w for w in items if w.status == flt.status]
        if flt.document_id:
            items = [w for w in items if w.document_id == flt.document_id]
        if flt.created_by:
            items = [w for w in items if w.created_by == flt.created_by]
        if flt.after is not None:
            items = [w for w in items if w.created_at >= flt.after]
        if flt.before is not None:
            items = [w for w in items if w.created_at <= flt.before]
        items.sort(key=lambda w: w.created_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedWorkflows(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> WorkflowStats:
        items = self._store.list_all()
        s = WorkflowStats(total_workflows=len(items))
        if not items:
            return s
        completed_durations: List[float] = []
        for wf in items:
            s.by_status[wf.status.value] = (
                s.by_status.get(wf.status.value, 0) + 1
            )
            s.by_type[wf.workflow_type.value] = (
                s.by_type.get(wf.workflow_type.value, 0) + 1
            )
            for t in wf.tasks:
                s.tasks_by_status[t.status.value] = (
                    s.tasks_by_status.get(t.status.value, 0) + 1
                )
                s.total_tasks += 1
            if wf.status == WorkflowStatus.COMPLETED:
                if wf.started_at and wf.completed_at:
                    completed_durations.append(
                        wf.completed_at - wf.started_at
                    )
            s.escalations_triggered += sum(
                1
                for a in wf.audit_trail
                if a.action == "workflow.escalated"
            )
            s.last_workflow_at = max(
                s.last_workflow_at or 0, wf.created_at
            )
        if completed_durations:
            s.average_completion_seconds = round(
                sum(completed_durations) / len(completed_durations), 3
            )
        completed = s.by_status.get(WorkflowStatus.COMPLETED.value, 0)
        terminal = completed + s.by_status.get(
            WorkflowStatus.CANCELLED.value, 0
        ) + s.by_status.get(WorkflowStatus.FAILED.value, 0)
        s.success_rate = round(
            completed / terminal, 4
        ) if terminal > 0 else 0.0
        return s


# ─── AutomationService (DI facade) ────────────────────────────────


class AutomationService:
    def __init__(self, store: WorkflowStore) -> None:
        self.store = store
        self.repository = WorkflowRepository(store)
        self.engine = WorkflowEngine()
        self.task_manager = TaskManager()
        self.orchestrator = WorkflowOrchestrator()

    # ── CRUD ──────────────────────────────────────────────────

    def create(self, request: WorkflowCreateRequest) -> Workflow:
        wf = self.engine.create(request)
        self.store.add(wf)
        return wf

    def get(self, workflow_id: str) -> Optional[Workflow]:
        return self.store.get(workflow_id)

    def search(self, flt: WorkflowFilter) -> PaginatedWorkflows:
        return self.repository.search(flt)

    def stats(self) -> WorkflowStats:
        return self.repository.stats()

    def list_all(self) -> List[Workflow]:
        return self.store.list_all()

    # ── Lifecycle ─────────────────────────────────────────────

    def start(
        self, workflow_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.start(wf, actor=actor)
        self.store.add(wf)
        return wf

    def pause(
        self, workflow_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.pause(wf, actor=actor)
        self.store.add(wf)
        return wf

    def resume(
        self, workflow_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.resume(wf, actor=actor)
        self.store.add(wf)
        return wf

    def cancel(
        self,
        workflow_id: str,
        actor: str = "system",
        reason: str = "",
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.cancel(wf, actor=actor, reason=reason)
        self.store.add(wf)
        return wf

    def complete(
        self, workflow_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.complete(wf, actor=actor)
        self.store.add(wf)
        return wf

    # ── Tasks ─────────────────────────────────────────────────

    def add_task(
        self, workflow_id: str, request: TaskCreateRequest
    ) -> Optional[TaskAssignment]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        task = self.task_manager.add_task(wf, request)
        self.store.add(wf)
        return task

    def assign_task(
        self,
        workflow_id: str,
        task_id: str,
        request: TaskAssignmentRequest,
        actor: str = "system",
    ) -> Optional[TaskAssignment]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        task = self.task_manager.assign(wf, task_id, request, actor=actor)
        self.store.add(wf)
        return task

    def start_task(
        self, workflow_id: str, task_id: str, actor: str = "system"
    ) -> Optional[TaskAssignment]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        task = self.task_manager.start_task(wf, task_id, actor=actor)
        self.store.add(wf)
        return task

    def complete_task(
        self,
        workflow_id: str,
        task_id: str,
        request: TaskCompletionRequest,
        actor: str = "system",
    ) -> Optional[TaskAssignment]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        task = self.task_manager.complete_task(
            wf, task_id, request, actor=actor
        )
        self.store.add(wf)
        return task

    # ── Escalation / Orchestration ────────────────────────────

    def escalate(
        self,
        workflow_id: str,
        request: EscalationRequest,
        actor: str = "system",
    ) -> Optional[Tuple[EscalationRule, Workflow]]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        rule = self.orchestrator.trigger_escalation(wf, request, actor=actor)
        self.store.add(wf)
        return rule, wf

    def progress_percent(self, workflow_id: str) -> float:
        wf = self.store.get(workflow_id)
        if wf is None:
            return 0.0
        return self.orchestrator.progress_percent(wf)

    def evaluate_timeouts(
        self, workflow_id: str
    ) -> List[EscalationRule]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return []
        return self.orchestrator.evaluate_timeouts(wf)

    def advance(
        self, workflow_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        wf = self.store.get(workflow_id)
        if wf is None:
            return None
        self.engine.advance_step(wf, actor=actor)
        self.store.add(wf)
        return wf

    # ── Cross-module integration ──────────────────────────────

    def create_from_recommendation(
        self, recommendation_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        rec = self._fetch_recommendation(recommendation_id)
        if rec is None:
            return None
        priority_map = {
            "P0": TaskPriority.URGENT,
            "P1": TaskPriority.HIGH,
            "P2": TaskPriority.MEDIUM,
            "P3": TaskPriority.LOW,
        }
        priority = priority_map.get(
            getattr(rec, "priority", "P2"), TaskPriority.MEDIUM
        )
        request = WorkflowCreateRequest(
            name=f"Workflow for {rec.title}",
            description=(
                f"Auto-generated workflow from recommendation "
                f"{recommendation_id}"
            ),
            workflow_type=WorkflowType.POLICY_UPDATE,
            source_recommendation_id=recommendation_id,
            document_id=getattr(rec, "document_id", None),
            created_by=actor,
            priority=priority,
            metadata={
                "recommendation_id": recommendation_id,
                "source": "recommendation_engine",
            },
        )
        wf = self.create(request)
        # Add a task per action_plan step if present
        plan = getattr(rec, "action_plan", None)
        if plan and getattr(plan, "steps", None) and wf.steps:
            for i, stp in enumerate(plan.steps[: len(wf.steps)]):
                target_step = wf.steps[i]
                self.task_manager.add_task(
                    wf,
                    TaskCreateRequest(
                        step_id=target_step.step_id,
                        title=stp.title or f"Step {i + 1}",
                        description=getattr(stp, "description", ""),
                        assignee=stp.owner,
                        priority=priority,
                        metadata={
                            "source_step": stp.step_id,
                        },
                    ),
                )
        self.store.add(wf)
        return wf

    def create_from_risk_assessment(
        self, assessment_id: str, actor: str = "system"
    ) -> Optional[Workflow]:
        assessment = self._fetch_risk_assessment(assessment_id)
        if assessment is None:
            return None
        wf_type = (
            WorkflowType.RISK_ASSESSMENT
            if assessment.risk_level.value in {"medium", "low"}
            else WorkflowType.REGULATORY_CHANGE_REVIEW
        )
        priority_map = {
            "low": TaskPriority.LOW,
            "medium": TaskPriority.MEDIUM,
            "high": TaskPriority.HIGH,
            "critical": TaskPriority.URGENT,
        }
        priority = priority_map.get(
            assessment.risk_level.value, TaskPriority.MEDIUM
        )
        request = WorkflowCreateRequest(
            name=f"Workflow for risk {assessment_id}",
            description=(
                f"Auto-generated workflow from risk assessment "
                f"{assessment_id}"
            ),
            workflow_type=wf_type,
            source_risk_assessment_id=assessment_id,
            document_id=assessment.document_id,
            created_by=actor,
            priority=priority,
            metadata={
                "risk_score": assessment.risk_score,
                "risk_level": assessment.risk_level.value,
            },
        )
        wf = self.create(request)
        # Add tasks for each recommended action
        for action in assessment.recommended_actions[: len(wf.steps) or 1]:
            target_step = wf.steps[0] if wf.steps else None
            if target_step is None:
                break
            self.task_manager.add_task(
                wf,
                TaskCreateRequest(
                    step_id=target_step.step_id,
                    title=action.title,
                    description=action.description,
                    priority=priority,
                    metadata={
                        "action_id": getattr(action, "action_id", ""),
                        "action_type": action.action_type.value,
                    },
                ),
            )
        self.store.add(wf)
        return wf

    @staticmethod
    def _fetch_recommendation(rid: str) -> Optional[Any]:
        try:
            from app.services.recommendations import (
                build_default_recommendation_service,
            )

            return build_default_recommendation_service().get(rid)
        except Exception:  # pragma: no cover
            return None

    @staticmethod
    def _fetch_risk_assessment(aid: str) -> Optional[Any]:
        try:
            from app.services.compliance_risk import (
                build_default_compliance_risk_service,
            )

            return build_default_compliance_risk_service().get(aid)
        except Exception:  # pragma: no cover
            return None


def build_default_automation_service() -> AutomationService:
    persist = os.path.join(
        settings.STORAGE_ROOT, "workflow", "workflows.jsonl"
    )
    store = InMemoryWorkflowStore(persist_path=persist)
    return AutomationService(store=store)


__all__ = [
    "WorkflowEngine",
    "TaskManager",
    "WorkflowOrchestrator",
    "WorkflowStore",
    "InMemoryWorkflowStore",
    "WorkflowRepository",
    "AutomationService",
    "build_default_automation_service",
]
