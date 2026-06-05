"""Module 8.5 — Human-in-the-Loop Review System.

Public surface
--------------
* ``ReviewEngine``             — lifecycle + audit
* ``ReviewManager``            — assignment, comments, corrections
* ``ApprovalCoordinator``      — multi-approver consensus
* ``ReviewRepository``         — search / stats / history
* ``ReviewStore`` (ABC) + ``InMemoryReviewStore``
* ``ReviewService``            — DI facade
* ``build_default_review_service``
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.schemas.review import (
    ApprovalRequirement,
    AuditEntry,
    PaginatedReviews,
    Review,
    ReviewComment,
    ReviewCorrection,
    ReviewCreateRequest,
    ReviewDecision,
    ReviewDecisionRequest,
    ReviewFilter,
    ReviewStats,
    ReviewStatus,
)
from app.services.observability import (
    get_review_metrics,
    track_request,
)

logger = logging.getLogger(__name__)


# ─── ReviewEngine ────────────────────────────────────────────────


class ReviewEngine:
    """State machine for review lifecycle."""

    _TERMINAL_STATUSES = {
        ReviewStatus.APPROVED,
        ReviewStatus.REJECTED,
        ReviewStatus.EXPIRED,
        ReviewStatus.WITHDRAWN,
    }

    def create(
        self, request: ReviewCreateRequest, actor: str = "system"
    ) -> Review:
        with track_request(
            endpoint="/api/v1/review/create",
            strategy="review_create",
        ):
            requirements = self._derive_requirements(request)
            review = Review(
                title=request.title,
                description=request.description,
                subject_type=request.subject_type,
                subject_id=request.subject_id,
                workflow_id=request.workflow_id,
                task_id=request.task_id,
                priority=request.priority,
                assigned_to=request.assigned_to,
                assigned_role=request.assigned_role,
                required_approvers=requirements,
                due_at=request.due_at,
                created_by=actor,
                metadata=request.metadata,
                audit_trail=[
                    AuditEntry(
                        action="review.created",
                        actor=actor,
                        details={
                            "subject_type": request.subject_type,
                            "subject_id": request.subject_id,
                        },
                    )
                ],
            )
            get_review_metrics().record_created(request.priority.value)
            get_review_metrics().record_status(ReviewStatus.PENDING.value)
            return review

    def start(
        self, review: Review, actor: str = "system"
    ) -> Review:
        if review.status not in (
            ReviewStatus.PENDING,
            ReviewStatus.IN_REVIEW,
        ):
            raise ValueError(
                f"Cannot start review in status {review.status.value}"
            )
        review.status = ReviewStatus.IN_REVIEW
        review.started_at = review.started_at or time.time()
        review.audit_trail.append(
            AuditEntry(
                action="review.started",
                actor=actor,
                details={"reviewer": review.assigned_to},
            )
        )
        get_review_metrics().record_started()
        get_review_metrics().record_status(ReviewStatus.IN_REVIEW.value)
        return review

    def complete(
        self,
        review: Review,
        decision: ReviewDecision,
        actor: str = "system",
    ) -> Review:
        if review.status == ReviewStatus.IN_REVIEW or decision in (
            ReviewDecision.APPROVED,
            ReviewDecision.REJECTED,
        ):
            review.status = (
                ReviewStatus.APPROVED
                if decision == ReviewDecision.APPROVED
                else ReviewStatus.REJECTED
            )
            review.decision = decision
            review.completed_at = time.time()
            review.audit_trail.append(
                AuditEntry(
                    action="review.decided",
                    actor=actor,
                    details={"decision": decision.value},
                )
            )
            latency = 0.0
            if review.started_at:
                latency = (
                    time.time() - review.started_at
                ) * 1000.0
            get_review_metrics().record_decision(
                decision=decision.value, latency_ms=latency
            )
            get_review_metrics().record_status(review.status.value)
            return review
        raise ValueError(
            f"Cannot complete review in status {review.status.value}"
        )

    def escalate(
        self, review: Review, actor: str = "system", reason: str = ""
    ) -> Review:
        review.status = ReviewStatus.ESCALATED
        review.audit_trail.append(
            AuditEntry(
                action="review.escalated",
                actor=actor,
                details={"reason": reason},
            )
        )
        get_review_metrics().record_decision("escalate")
        get_review_metrics().record_status(ReviewStatus.ESCALATED.value)
        return review

    def withdraw(
        self, review: Review, actor: str = "system", reason: str = ""
    ) -> Review:
        review.status = ReviewStatus.WITHDRAWN
        review.completed_at = time.time()
        review.audit_trail.append(
            AuditEntry(
                action="review.withdrawn",
                actor=actor,
                details={"reason": reason},
            )
        )
        get_review_metrics().record_status(ReviewStatus.WITHDRAWN.value)
        return review

    def is_terminal(self, review: Review) -> bool:
        return review.status in self._TERMINAL_STATUSES

    @staticmethod
    def _derive_requirements(
        request: ReviewCreateRequest,
    ) -> List[ApprovalRequirement]:
        if request.required_approvers:
            return list(request.required_approvers)
        # Default single-approver requirement
        return [
            ApprovalRequirement(
                approver_role=request.assigned_role or "reviewer",
                required=True,
                min_approvals=1,
            )
        ]


# ─── ReviewManager ───────────────────────────────────────────────


class ReviewManager:
    """Manage comments, corrections, and assignment on a review."""

    def assign(
        self,
        review: Review,
        assignee: str,
        role: str = "",
        actor: str = "system",
    ) -> Review:
        review.assigned_to = assignee
        if role:
            review.assigned_role = role
        review.assigned_at = time.time()
        review.audit_trail.append(
            AuditEntry(
                action="review.assigned",
                actor=actor,
                details={"assignee": assignee, "role": role},
            )
        )
        return review

    def add_comment(
        self,
        review: Review,
        author: str,
        text: str,
        role: str = "reviewer",
    ) -> ReviewComment:
        if not text:
            raise ValueError("Comment text cannot be empty")
        comment = ReviewComment(
            author=author,
            role=role,
            text=text,
        )
        review.comments.append(comment)
        review.audit_trail.append(
            AuditEntry(
                action="review.comment_added",
                actor=author,
                details={"comment_id": comment.comment_id, "role": role},
            )
        )
        get_review_metrics().record_comment(role=role)
        return comment

    def add_correction(
        self,
        review: Review,
        field: str,
        original_value: str,
        corrected_value: str,
        reason: str,
        corrected_by: str,
    ) -> ReviewCorrection:
        correction = ReviewCorrection(
            field=field,
            original_value=original_value,
            corrected_value=corrected_value,
            reason=reason,
            corrected_by=corrected_by,
        )
        review.corrections.append(correction)
        review.audit_trail.append(
            AuditEntry(
                action="review.correction_recorded",
                actor=corrected_by,
                details={
                    "correction_id": correction.correction_id,
                    "field": field,
                },
            )
        )
        get_review_metrics().record_correction()
        return correction


# ─── ApprovalCoordinator ────────────────────────────────────────


class ApprovalCoordinator:
    """Coordinate multi-approver consensus on a review."""

    def evaluate(
        self, review: Review
    ) -> Dict[str, Any]:
        """Compute current approval state."""
        result: Dict[str, Any] = {
            "fully_approved": False,
            "rejected": False,
            "pending_approvals": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "total_requirements": len(review.required_approvers),
        }
        for req in review.required_approvers:
            if req.rejected_by:
                result["rejected_count"] += 1
                result["rejected"] = True
            elif len(req.approved_by) >= req.min_approvals:
                result["approved_count"] += 1
            else:
                result["pending_approvals"] += 1
        result["fully_approved"] = (
            result["pending_approvals"] == 0
            and result["approved_count"] == result["total_requirements"]
            and not result["rejected"]
        )
        return result

    def record_approval(
        self,
        review: Review,
        approver: str,
        role: str = "",
        actor: str = "system",
    ) -> Review:
        # Find the matching requirement (by role if specified, else first)
        target: Optional[ApprovalRequirement] = None
        for req in review.required_approvers:
            if role and req.approver_role == role:
                target = req
                break
        if target is None:
            for req in review.required_approvers:
                if approver not in req.approved_by:
                    target = req
                    break
        if target is None:
            raise ValueError("No matching approval requirement")
        if approver in target.approved_by:
            return review  # idempotent
        target.approved_by.append(approver)
        review.audit_trail.append(
            AuditEntry(
                action="review.approval_recorded",
                actor=actor,
                details={"approver": approver, "role": target.approver_role},
            )
        )
        return review

    def record_rejection(
        self,
        review: Review,
        approver: str,
        reason: str,
        role: str = "",
        actor: str = "system",
    ) -> Review:
        target: Optional[ApprovalRequirement] = None
        for req in review.required_approvers:
            if role and req.approver_role == role:
                target = req
                break
        if target is None:
            target = (
                review.required_approvers[0]
                if review.required_approvers
                else None
            )
        if target is None:
            raise ValueError("No matching approval requirement")
        target.rejected_by.append(approver)
        review.audit_trail.append(
            AuditEntry(
                action="review.rejection_recorded",
                actor=actor,
                details={
                    "approver": approver,
                    "role": target.approver_role,
                    "reason": reason,
                },
            )
        )
        return review


# ─── Store ───────────────────────────────────────────────────────


class ReviewStore(ABC):
    @abstractmethod
    def add(self, review: Review) -> None: ...

    @abstractmethod
    def get(self, review_id: str) -> Optional[Review]: ...

    @abstractmethod
    def list_all(self) -> List[Review]: ...

    @abstractmethod
    def reset(self) -> None: ...


class InMemoryReviewStore(ReviewStore):
    def __init__(self, persist_path: Optional[str] = None) -> None:
        self._lock = threading.RLock()
        self._items: Dict[str, Review] = {}
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
                        r = Review(**data)
                        self._items[r.review_id] = r
                    except Exception:  # pragma: no cover
                        continue
        except Exception:  # pragma: no cover
            pass

    def _persist(self, r: Review) -> None:
        if not self._persist_path:
            return
        try:
            os.makedirs(os.path.dirname(self._persist_path), exist_ok=True)
            with open(self._persist_path, "a", encoding="utf-8") as f:
                f.write(r.model_dump_json() + "\n")
        except Exception:  # pragma: no cover
            pass

    def add(self, r: Review) -> None:
        with self._lock:
            self._items[r.review_id] = r
        self._persist(r)

    def get(self, rid: str) -> Optional[Review]:
        with self._lock:
            return self._items.get(rid)

    def list_all(self) -> List[Review]:
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


# ─── Repository ─────────────────────────────────────────────────


class ReviewRepository:
    def __init__(self, store: ReviewStore) -> None:
        self._store = store

    def add(self, r: Review) -> None:
        self._store.add(r)

    def get(self, rid: str) -> Optional[Review]:
        return self._store.get(rid)

    def search(self, flt: ReviewFilter) -> PaginatedReviews:
        items = self._store.list_all()
        if flt.status:
            items = [r for r in items if r.status == flt.status]
        if flt.priority:
            items = [r for r in items if r.priority == flt.priority]
        if flt.assigned_to:
            items = [r for r in items if r.assigned_to == flt.assigned_to]
        if flt.workflow_id:
            items = [r for r in items if r.workflow_id == flt.workflow_id]
        if flt.subject_type:
            items = [r for r in items if r.subject_type == flt.subject_type]
        if flt.subject_id:
            items = [r for r in items if r.subject_id == flt.subject_id]
        if flt.after is not None:
            items = [r for r in items if r.created_at >= flt.after]
        if flt.before is not None:
            items = [r for r in items if r.created_at <= flt.before]
        items.sort(key=lambda r: r.created_at, reverse=True)
        total = len(items)
        start = (flt.page - 1) * flt.page_size
        end = start + flt.page_size
        return PaginatedReviews(
            items=items[start:end],
            total=total,
            page=flt.page,
            page_size=flt.page_size,
            has_more=end < total,
        )

    def stats(self) -> ReviewStats:
        items = self._store.list_all()
        s = ReviewStats(total_reviews=len(items))
        if not items:
            return s
        latencies: List[float] = []
        for r in items:
            s.by_status[r.status.value] = (
                s.by_status.get(r.status.value, 0) + 1
            )
            s.by_priority[r.priority.value] = (
                s.by_priority.get(r.priority.value, 0) + 1
            )
            s.by_decision[r.decision.value] = (
                s.by_decision.get(r.decision.value, 0) + 1
            )
            s.total_comments += len(r.comments)
            s.total_corrections += len(r.corrections)
            if r.status == ReviewStatus.APPROVED:
                s.approved += 1
            elif r.status == ReviewStatus.REJECTED:
                s.rejected += 1
            elif r.status == ReviewStatus.ESCALATED:
                s.escalated += 1
            elif r.status == ReviewStatus.PENDING:
                s.pending += 1
            if r.started_at and r.completed_at:
                latencies.append(
                    (r.completed_at - r.started_at) * 1000.0
                )
            s.last_review_at = max(s.last_review_at or 0, r.created_at)
        decided = s.approved + s.rejected
        s.approval_rate = round(
            s.approved / decided, 4
        ) if decided > 0 else 0.0
        if latencies:
            s.average_latency_ms = round(
                sum(latencies) / len(latencies), 3
            )
        return s

    def history_for(self, rid: str) -> List[Review]:
        review = self._store.get(rid)
        if review is None:
            return []
        return [review]

    def queue_for(self, assignee: str) -> List[Review]:
        return [
            r
            for r in self._store.list_all()
            if r.assigned_to == assignee
            and r.status
            in (ReviewStatus.PENDING, ReviewStatus.IN_REVIEW)
        ]


# ─── ReviewService (DI facade) ──────────────────────────────────


class ReviewService:
    def __init__(self, store: ReviewStore) -> None:
        self.store = store
        self.repository = ReviewRepository(store)
        self.engine = ReviewEngine()
        self.manager = ReviewManager()
        self.approver = ApprovalCoordinator()

    # ── CRUD ─────────────────────────────────────────────────

    def create(
        self, request: ReviewCreateRequest, actor: str = "system"
    ) -> Review:
        review = self.engine.create(request, actor=actor)
        self.store.add(review)
        return review

    def get(self, rid: str) -> Optional[Review]:
        return self.store.get(rid)

    def search(self, flt: ReviewFilter) -> PaginatedReviews:
        return self.repository.search(flt)

    def stats(self) -> ReviewStats:
        return self.repository.stats()

    def list_all(self) -> List[Review]:
        return self.store.list_all()

    def queue_for(self, assignee: str) -> List[Review]:
        return self.repository.queue_for(assignee)

    # ── Lifecycle ────────────────────────────────────────────

    def start(
        self, rid: str, actor: str = "system"
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        self.engine.start(review, actor=actor)
        self.store.add(review)
        return review

    def decide(
        self,
        rid: str,
        request: ReviewDecisionRequest,
        actor: str = "system",
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        # Add comment if supplied
        if request.comment_text:
            self.manager.add_comment(
                review,
                author=actor,
                text=request.comment_text,
                role=review.assigned_role or "reviewer",
            )
        # Record corrections if supplied
        for corr in request.corrections:
            self.manager.add_correction(
                review,
                field=corr.field,
                original_value=corr.original_value,
                corrected_value=corr.corrected_value,
                reason=corr.reason,
                corrected_by=actor,
            )
        # Apply approval consensus logic
        decision = request.decision
        if decision in (
            ReviewDecision.APPROVED,
            ReviewDecision.REJECTED,
        ):
            if decision == ReviewDecision.APPROVED:
                self.approver.record_approval(
                    review,
                    approver=actor,
                    role=request.approver_role,
                )
            else:
                self.approver.record_rejection(
                    review,
                    approver=actor,
                    reason=request.reason or "",
                    role=request.approver_role,
                )
            consensus = self.approver.evaluate(review)
            if consensus["rejected"]:
                self.engine.complete(
                    review, ReviewDecision.REJECTED, actor=actor
                )
            elif consensus["fully_approved"]:
                self.engine.complete(
                    review, ReviewDecision.APPROVED, actor=actor
                )
            # Otherwise keep IN_REVIEW pending other approvers
        elif decision == ReviewDecision.ESCALATE:
            self.engine.escalate(
                review, actor=actor, reason=request.reason or ""
            )
        elif decision == ReviewDecision.NEEDS_CHANGES:
            review.decision = decision
            review.audit_trail.append(
                AuditEntry(
                    action="review.needs_changes",
                    actor=actor,
                    details={"reason": request.reason},
                )
            )
        self.store.add(review)
        return review

    def escalate(
        self, rid: str, reason: str = "", actor: str = "system"
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        self.engine.escalate(review, actor=actor, reason=reason)
        self.store.add(review)
        return review

    def withdraw(
        self, rid: str, reason: str = "", actor: str = "system"
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        self.engine.withdraw(review, actor=actor, reason=reason)
        self.store.add(review)
        return review

    # ── Comments / corrections ───────────────────────────────

    def add_comment(
        self,
        rid: str,
        text: str,
        author: str,
        role: str = "reviewer",
    ) -> Optional[ReviewComment]:
        review = self.store.get(rid)
        if review is None:
            return None
        c = self.manager.add_comment(review, author, text, role)
        self.store.add(review)
        return c

    def add_correction(
        self,
        rid: str,
        field: str,
        original_value: str,
        corrected_value: str,
        reason: str,
        corrected_by: str,
    ) -> Optional[ReviewCorrection]:
        review = self.store.get(rid)
        if review is None:
            return None
        c = self.manager.add_correction(
            review, field, original_value, corrected_value, reason, corrected_by
        )
        self.store.add(review)
        return c

    # ── Approval coordinator ─────────────────────────────────

    def evaluate_approvals(self, rid: str) -> Optional[Dict[str, Any]]:
        review = self.store.get(rid)
        if review is None:
            return None
        return self.approver.evaluate(review)

    def record_approval(
        self,
        rid: str,
        approver: str,
        role: str = "",
        actor: str = "system",
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        self.approver.record_approval(review, approver, role, actor=actor)
        consensus = self.approver.evaluate(review)
        if consensus["fully_approved"]:
            self.engine.complete(
                review, ReviewDecision.APPROVED, actor=actor
            )
        self.store.add(review)
        return review

    def record_rejection(
        self,
        rid: str,
        approver: str,
        reason: str,
        role: str = "",
        actor: str = "system",
    ) -> Optional[Review]:
        review = self.store.get(rid)
        if review is None:
            return None
        self.approver.record_rejection(
            review, approver, reason, role, actor=actor
        )
        self.engine.complete(
            review, ReviewDecision.REJECTED, actor=actor
        )
        self.store.add(review)
        return review

    # ── Cross-module integration ─────────────────────────────

    def create_for_workflow(
        self,
        workflow_id: str,
        title: str = "Workflow review",
        assigned_to: str = "compliance_head",
        actor: str = "system",
    ) -> Optional[Review]:
        try:
            from app.services.workflow import (
                build_default_automation_service,
            )
            wf = build_default_automation_service().get(workflow_id)
            if wf is None:
                return None
            request = ReviewCreateRequest(
                title=title,
                description=(
                    f"Review of workflow {workflow_id} "
                    f"({wf.workflow_type.value})"
                ),
                subject_type="workflow",
                subject_id=workflow_id,
                workflow_id=workflow_id,
                assigned_to=assigned_to,
                assigned_role="reviewer",
                created_by=actor,
            )
            return self.create(request, actor=actor)
        except Exception as e:  # pragma: no cover
            logger.debug("create_for_workflow failed: %s", e)
            return None


def build_default_review_service() -> ReviewService:
    persist = os.path.join(
        settings.STORAGE_ROOT, "review", "reviews.jsonl"
    )
    store = InMemoryReviewStore(persist_path=persist)
    return ReviewService(store=store)


__all__ = [
    "ReviewEngine",
    "ReviewManager",
    "ApprovalCoordinator",
    "ReviewStore",
    "InMemoryReviewStore",
    "ReviewRepository",
    "ReviewService",
    "build_default_review_service",
]
