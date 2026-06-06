"""Module 9 — Multi-Agent Framework API."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, status

from app.schemas.agents import (
    AgentDiscoveryQuery,
    AgentExecutionRequest,
    AgentHealthCheck,
    AgentMetadata,
    AgentRegistrationRequest,
    AgentResult,
    CapabilityKind,
    CoordinatorRequest,
    CoordinatorResult,
    PaginatedAgents,
)
from app.services.agents import AgentFrameworkService
from app.services.observability import get_agent_metrics

router = APIRouter(prefix="/agents", tags=["agents"])


def _service_dep():
    from app.api.dependencies import get_agent_framework_service

    return Depends(get_agent_framework_service)


# ─── Health / Stats ────────────────────────────────────────────


@router.get("/health")
async def health() -> Dict[str, Any]:
    metrics = get_agent_metrics()
    return {
        "status": "ok",
        "module": "agents",
        "metrics": metrics.snapshot(),
    }


# ─── Registry ─────────────────────────────────────────────────


@router.post(
    "/agents",
    response_model=AgentMetadata,
    status_code=status.HTTP_201_CREATED,
)
async def register_agent(
    request: AgentRegistrationRequest,
    svc: AgentFrameworkService = _service_dep(),
) -> AgentMetadata:
    """Register a new agent.

    Note: the body of this endpoint registers a *metadata-only* echo
    agent. Programmatic registration with a real :class:`BaseAgent`
    instance is supported by the service directly; this endpoint
    exists so that the framework can be exercised end-to-end via
    HTTP.
    """
    from app.services.agents import CapabilityAgent, EchoAgent

    if request.name == "echo-agent":
        from app.schemas.agents import AgentMetadata as _AM

        instance = EchoAgent(
            _AM(
                name=request.name,
                description=request.description,
                capabilities=request.capabilities,
                tags=request.tags,
            )
        )
    else:
        # For unknown names, we still register a CapabilityAgent whose
        # default handler just returns the input back. This keeps the
        # framework usable for any name without a custom handler.
        from app.schemas.agents import AgentMetadata as _AM

        async def _default_handler(task):
            return {"agent": request.name, "input": task.input}

        instance = CapabilityAgent(
            _AM(
                name=request.name,
                description=request.description,
                capabilities=request.capabilities,
                tags=request.tags,
            ),
            handler=_default_handler,
        )
    return svc.register(request, instance)


@router.delete("/agents/{name}")
async def unregister_agent(
    name: str, svc: AgentFrameworkService = _service_dep()
) -> Dict[str, Any]:
    if not svc.unregister(name):
        raise HTTPException(status_code=404, detail="agent not found")
    return {"unregistered": name}


@router.get("/agents", response_model=PaginatedAgents)
async def list_agents(
    capability: Optional[str] = None,
    text_query: Optional[str] = None,
    tag: Optional[str] = None,
    healthy_only: bool = False,
    page: int = 1,
    page_size: int = 50,
    svc: AgentFrameworkService = _service_dep(),
) -> PaginatedAgents:
    try:
        cap_kind = CapabilityKind(capability) if capability else None
    except ValueError:
        cap_kind = None
    query = AgentDiscoveryQuery(
        capability=cap_kind,
        text_query=text_query or None,
        tag=tag or None,
        healthy_only=healthy_only,
        page=max(1, page),
        page_size=max(1, min(200, page_size)),
    )
    return svc.search_agents(query)


@router.get("/agents/{name}", response_model=AgentMetadata)
async def get_agent(
    name: str, svc: AgentFrameworkService = _service_dep()
) -> AgentMetadata:
    meta = svc.get_agent(name)
    if meta is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return meta


@router.get("/agents/{name}/health", response_model=AgentHealthCheck)
async def get_agent_health(
    name: str, svc: AgentFrameworkService = _service_dep()
) -> AgentHealthCheck:
    h = svc.health(name)
    if h is None:
        raise HTTPException(status_code=404, detail="agent not found")
    return h


# ─── Execution ───────────────────────────────────────────────


@router.post("/execute", response_model=AgentResult)
async def execute_agent(
    request: AgentExecutionRequest,
    svc: AgentFrameworkService = _service_dep(),
) -> AgentResult:
    return await svc.execute(request)


# ─── Coordinator ─────────────────────────────────────────────


@router.post(
    "/coordinate",
    response_model=CoordinatorResult,
    status_code=status.HTTP_200_OK,
)
async def coordinate(
    request: CoordinatorRequest,
    svc: AgentFrameworkService = _service_dep(),
) -> CoordinatorResult:
    return await svc.coordinate(request)


__all__ = ["router"]
