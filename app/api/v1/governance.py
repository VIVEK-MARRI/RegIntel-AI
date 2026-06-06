"""Module 8.6 — AI Governance Layer API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.schemas.governance import (
    ApprovalPolicy,
    ApprovalPolicyCreateRequest,
    DecisionRegistryFilter,
    DecisionType,
    GovernanceDecision,
    GovernanceDecisionCreateRequest,
    GovernancePolicy,
    GovernancePolicyCreateRequest,
    GovernanceStats,
    PaginatedDecisions,
    PolicyCheckResult,
    PolicyScope,
)
from app.services.governance import GovernanceService
from app.services.observability import get_governance_metrics

router = APIRouter(prefix="/governance", tags=["governance"])


def _service_dep():
    from app.api.dependencies import get_governance_service

    return Depends(get_governance_service)


# ─── Health / Stats ────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_governance_metrics()
    return {
        "status": "ok",
        "module": "governance",
        "metrics": metrics.snapshot(),
    }


@router.get("/stats", response_model=GovernanceStats)
async def stats(svc: GovernanceService = _service_dep()) -> GovernanceStats:
    return svc.stats()


# ─── Policy CRUD ──────────────────────────────────────────────


@router.post(
    "/policies",
    response_model=GovernancePolicy,
    status_code=status.HTTP_201_CREATED,
)
async def create_policy(
    request: GovernancePolicyCreateRequest,
    svc: GovernanceService = _service_dep(),
) -> GovernancePolicy:
    return svc.create_policy(request)


@router.get("/policies", response_model=List[GovernancePolicy])
async def list_policies(
    scope: Optional[str] = None,
    enabled_only: bool = False,
    svc: GovernanceService = _service_dep(),
) -> List[GovernancePolicy]:
    sc = PolicyScope(scope) if scope else None
    return svc.list_policies(scope=sc, enabled_only=enabled_only)


@router.get("/policies/{policy_id}", response_model=GovernancePolicy)
async def get_policy(
    policy_id: str, svc: GovernanceService = _service_dep()
) -> GovernancePolicy:
    p = svc.get_policy(policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="policy not found")
    return p


@router.patch("/policies/{policy_id}", response_model=GovernancePolicy)
async def update_policy(
    policy_id: str,
    enabled: Optional[bool] = None,
    name: Optional[str] = None,
    description: Optional[str] = None,
    svc: GovernanceService = _service_dep(),
) -> GovernancePolicy:
    p = svc.update_policy(
        policy_id,
        enabled=enabled,
        name=name,
        description=description,
    )
    if p is None:
        raise HTTPException(status_code=404, detail="policy not found")
    return p


@router.delete("/policies/{policy_id}")
async def delete_policy(
    policy_id: str, svc: GovernanceService = _service_dep()
) -> Response:
    if not svc.delete_policy(policy_id):
        raise HTTPException(status_code=404, detail="policy not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Approval policies ────────────────────────────────────────


@router.post(
    "/approval-policies",
    response_model=ApprovalPolicy,
    status_code=status.HTTP_201_CREATED,
)
async def create_approval_policy(
    request: ApprovalPolicyCreateRequest,
    svc: GovernanceService = _service_dep(),
) -> ApprovalPolicy:
    return svc.create_approval_policy(request)


@router.get(
    "/approval-policies", response_model=List[ApprovalPolicy]
)
async def list_approval_policies(
    svc: GovernanceService = _service_dep(),
) -> List[ApprovalPolicy]:
    return svc.list_approval_policies()


@router.get(
    "/approval-policies/{policy_id}", response_model=ApprovalPolicy
)
async def get_approval_policy(
    policy_id: str, svc: GovernanceService = _service_dep()
) -> ApprovalPolicy:
    p = svc.get_approval_policy(policy_id)
    if p is None:
        raise HTTPException(status_code=404, detail="approval policy not found")
    return p


@router.delete("/approval-policies/{policy_id}")
async def delete_approval_policy(
    policy_id: str, svc: GovernanceService = _service_dep()
) -> Response:
    if not svc.delete_approval_policy(policy_id):
        raise HTTPException(
            status_code=404, detail="approval policy not found"
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ─── Decision registry ───────────────────────────────────────


@router.post(
    "/decisions",
    response_model=GovernanceDecision,
    status_code=status.HTTP_201_CREATED,
)
async def register_decision(
    request: GovernanceDecisionCreateRequest,
    svc: GovernanceService = _service_dep(),
) -> GovernanceDecision:
    return svc.register_decision(request)


@router.get("/decisions", response_model=PaginatedDecisions)
async def list_decisions(
    decision_type: Optional[str] = None,
    model_id: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    risk_level: Optional[str] = None,
    policy_compliant: Optional[bool] = None,
    actor: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: GovernanceService = _service_dep(),
) -> PaginatedDecisions:
    flt = DecisionRegistryFilter(
        decision_type=DecisionType(decision_type) if decision_type else None,
        model_id=model_id or None,
        subject_type=subject_type or None,
        subject_id=subject_id or None,
        risk_level=risk_level or None,
        policy_compliant=policy_compliant,
        actor=actor or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.search_decisions(flt)


@router.get("/decisions/{decision_id}", response_model=GovernanceDecision)
async def get_decision(
    decision_id: str, svc: GovernanceService = _service_dep()
) -> GovernanceDecision:
    d = svc.get_decision(decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return d


@router.post(
    "/decisions/{decision_id}/check",
    response_model=PolicyCheckResult,
)
async def recheck_decision(
    decision_id: str, svc: GovernanceService = _service_dep()
) -> PolicyCheckResult:
    d = svc.get_decision(decision_id)
    if d is None:
        raise HTTPException(status_code=404, detail="decision not found")
    return svc.check_decision(d)
