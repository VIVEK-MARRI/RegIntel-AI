"""Module 8.7 — Audit & Compliance Platform API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.audit import (
    AuditAction,
    AuditEvidence,
    AuditEvidenceCreateRequest,
    AuditFilter,
    AuditRecord,
    AuditRecordCreateRequest,
    AuditSeverity,
    AuditStats,
    ComplianceReport,
    ComplianceReportCreateRequest,
    DecisionLineage,
    PaginatedAuditRecords,
)
from app.services.audit import AuditService
from app.services.observability import get_audit_metrics

router = APIRouter(prefix="/audit", tags=["audit"])


def _service_dep():
    from app.api.dependencies import get_audit_service

    return Depends(get_audit_service)


# ─── Health / Stats ────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_audit_metrics()
    return {
        "status": "ok",
        "module": "audit",
        "metrics": metrics.snapshot(),
    }


@router.get("/stats", response_model=AuditStats)
async def stats(svc: AuditService = _service_dep()) -> AuditStats:
    return svc.stats()


# ─── Records ──────────────────────────────────────────────────


@router.post(
    "/records",
    response_model=AuditRecord,
    status_code=status.HTTP_201_CREATED,
)
async def create_record(
    request: AuditRecordCreateRequest,
    svc: AuditService = _service_dep(),
) -> AuditRecord:
    return svc.create_record(request)


@router.get("/records", response_model=PaginatedAuditRecords)
async def list_records(
    action: Optional[str] = None,
    severity: Optional[str] = None,
    actor: Optional[str] = None,
    subject_type: Optional[str] = None,
    subject_id: Optional[str] = None,
    source_module: Optional[str] = None,
    after: Optional[float] = None,
    before: Optional[float] = None,
    text_query: Optional[str] = None,
    page: int = 1,
    page_size: int = 50,
    svc: AuditService = _service_dep(),
) -> PaginatedAuditRecords:
    flt = AuditFilter(
        action=AuditAction(action) if action else None,
        severity=AuditSeverity(severity) if severity else None,
        actor=actor or None,
        subject_type=subject_type or None,
        subject_id=subject_id or None,
        source_module=source_module or None,
        after=after,
        before=before,
        text_query=text_query or None,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.search_records(flt)


@router.get("/records/{audit_id}", response_model=AuditRecord)
async def get_record(audit_id: str, svc: AuditService = _service_dep()) -> AuditRecord:
    rec = svc.get_record(audit_id)
    if rec is None:
        raise HTTPException(status_code=404, detail="record not found")
    return rec


# ─── Chain integrity ──────────────────────────────────────────


@router.get("/integrity")
async def chain_integrity(svc: AuditService = _service_dep()) -> Dict[str, Any]:
    intact, message = svc.verify_chain()
    stats = svc.repository.stats()
    total = stats.total_records
    valid = total if intact else 0
    invalid = 0 if intact else max(total, 1)
    return {
        "intact": intact,
        "message": message,
        "total": total,
        "valid": valid,
        "invalid": invalid,
        "chain_length": stats.chain_length,
        "last_chain_hash": stats.last_chain_hash,
    }


# ─── Evidence ─────────────────────────────────────────────────


@router.post(
    "/evidence",
    response_model=AuditEvidence,
    status_code=status.HTTP_201_CREATED,
)
async def add_evidence(
    request: AuditEvidenceCreateRequest,
    svc: AuditService = _service_dep(),
) -> AuditEvidence:
    return svc.add_evidence(request)


@router.get("/evidence", response_model=List[AuditEvidence])
async def list_evidence(
    record_id: Optional[str] = None,
    svc: AuditService = _service_dep(),
) -> List[AuditEvidence]:
    return svc.list_evidence(record_id=record_id or "")


@router.get("/evidence/{evidence_id}", response_model=AuditEvidence)
async def get_evidence(
    evidence_id: str, svc: AuditService = _service_dep()
) -> AuditEvidence:
    ev = svc.get_evidence(evidence_id)
    if ev is None:
        raise HTTPException(status_code=404, detail="evidence not found")
    return ev


# ─── Lineage ──────────────────────────────────────────────────


@router.get("/lineage/{root_decision_id}", response_model=DecisionLineage)
async def get_lineage(
    root_decision_id: str,
    subject_type: str = "decision",
    subject_id: str = "",
    svc: AuditService = _service_dep(),
) -> DecisionLineage:
    return svc.build_lineage(
        root_decision_id,
        subject_type=subject_type,
        subject_id=subject_id,
    )


# ─── Reports ──────────────────────────────────────────────────


@router.post(
    "/reports",
    response_model=ComplianceReport,
    status_code=status.HTTP_201_CREATED,
)
async def generate_report(
    request: ComplianceReportCreateRequest,
    svc: AuditService = _service_dep(),
) -> ComplianceReport:
    return svc.generate_report(request)


@router.get("/reports", response_model=List[ComplianceReport])
async def list_reports(
    kind: Optional[str] = None,
    svc: AuditService = _service_dep(),
) -> List[ComplianceReport]:
    items = svc.list_reports()
    if kind:
        items = [r for r in items if r.kind.value == kind]
    return items


@router.get("/reports/{report_id}", response_model=ComplianceReport)
async def get_report(
    report_id: str, svc: AuditService = _service_dep()
) -> ComplianceReport:
    rep = svc.get_report(report_id)
    if rep is None:
        raise HTTPException(status_code=404, detail="report not found")
    return rep


__all__ = ["router"]
