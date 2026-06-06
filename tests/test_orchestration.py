"""Tests for Module 9.8 — Multi-Agent Orchestration Platform."""

from __future__ import annotations

import os

# Lift rate-limit ceiling
os.environ.setdefault("RATE_LIMIT_PER_MINUTE", "100000")

import pytest

from httpx import ASGITransport, AsyncClient

from app.main import app
from app.schemas.agents import (
    AgentMetadata,
    AgentRegistrationRequest,
    AgentCapability,
    CapabilityKind,
    AgentResult,
    TaskStatus,
)
from app.schemas.orchestration import (
    AgentExecutionGraph,
    AgentExecutionStep,
    AgentMessage,
    AgentWorkflow,
    ExecutionMode,
    MessageKind,
    OrchestrationRequest,
    OrchestrationResult,
    SharedExecutionContext,
    SharedEvidenceItem,
    WorkflowDefinition,
    WorkflowStatus,
)
from app.services.agents import AgentMetadataStore, AgentFrameworkService, AgentRegistry
from app.services.orchestration import (
    AgentMessageBus,
    AgentOrchestrator,
    AgentSelectionPolicy,
    AgentWorkflowManager,
    CapabilityBasedRouter,
    ConflictResolver,
    ConsensusBuilder,
    EvidenceAggregator,
    ExecutionContextManager,
    OrchestrationEngine,
    OrchestrationService,
    ResultSynthesizer,
    SharedEvidenceStore,
    TaskCoordinator,
    build_default_orchestration_service,
)


# ─── Test fakes ───────────────────────────────────────────────


class _StubAgent:
    def __init__(self, name: str, output: dict = None) -> None:
        self.name = name
        self.metadata = AgentMetadata(
            name=name,
            capabilities=[
                AgentCapability(
                    kind=CapabilityKind.OTHER, name="stub"
                )
            ],
        )
        self._output = output or {"echo": True, "summary": f"result of {name}"}
        self._calls: int = 0

    def supports(self, kind: CapabilityKind) -> bool:
        return True

    def health(self):
        class _H:
            healthy = True

        return _H()

    async def execute(self, task) -> AgentResult:
        self._calls += 1
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.metadata.agent_id,
            agent_name=self.name,
            status=TaskStatus.SUCCEEDED,
            output={
                **self._output,
                "summary": self._output.get("summary", f"result of {self.name}"),
                "confidence": 0.7,
            },
        )


class _FailingAgent:
    def __init__(self, name: str = "failing-agent") -> None:
        self.name = name
        self.metadata = AgentMetadata(
            name=name,
            capabilities=[
                AgentCapability(
                    kind=CapabilityKind.OTHER, name="stub"
                )
            ],
        )

    def supports(self, kind: CapabilityKind) -> bool:
        return True

    def health(self):
        class _H:
            healthy = False

        return _H()

    async def execute(self, task) -> AgentResult:
        return AgentResult(
            task_id=task.task_id,
            agent_id=self.metadata.agent_id,
            agent_name=self.name,
            status=TaskStatus.FAILED,
            error="boom",
        )


class _StubFramework:
    """Stand-in for AgentFrameworkService used by the engine."""

    def __init__(self, agents) -> None:
        self.agents = agents
        self._by_name = {a.name: a for a in agents}

    def list_agents(self):
        return [
            type("M", (), {"name": a.name, "agent_id": a.name})()
            for a in self.agents
        ]

    @property
    def registry(self):
        class _R:
            def __init__(self, agents):
                self._agents = agents
                self._by_name = {a.name: a for a in agents}

            def list_instances(self):
                return list(self._agents)

            def get(self, name):
                return self._by_name.get(name)

        return _R(self.agents)

    async def execute(self, request) -> AgentResult:
        a = self._by_name.get(request.agent_name)
        if a is None:
            return AgentResult(
                task_id="",
                agent_id="",
                agent_name=request.agent_name,
                status=TaskStatus.FAILED,
                error="not found",
            )
        return await a.execute(
            type("_T", (), {
                "task_id": "t",
                "input": request.input,
                "context": request.context,
                "capability": request.capability,
                "max_retries": request.max_retries or 0,
                "timeout_ms": request.timeout_ms,
            })()
        )


# ─── Message bus ──────────────────────────────────────────────


def test_message_bus_publish_and_history():
    bus = AgentMessageBus()
    received: list = []
    bus.subscribe("a", lambda m: received.append(m))
    bus.publish(
        AgentMessage(
            from_agent="x", to_agent="a", kind=MessageKind.TASK
        )
    )
    assert len(received) == 1
    assert bus.message_count == 1
    assert bus.history()[0].from_agent == "x"


def test_message_bus_wildcard_subscriber():
    bus = AgentMessageBus()
    received: list = []
    bus.subscribe("*", lambda m: received.append(m))
    bus.publish(
        AgentMessage(
            from_agent="x", to_agent="a", kind=MessageKind.TASK
        )
    )
    assert len(received) == 1


def test_message_bus_history_filters():
    bus = AgentMessageBus()
    bus.publish(
        AgentMessage(
            from_agent="x", to_agent="a", kind=MessageKind.TASK
        )
    )
    bus.publish(
        AgentMessage(
            from_agent="x", to_agent="b", kind=MessageKind.RESULT
        )
    )
    assert len(bus.history(from_agent="x", to_agent="a")) == 1
    assert len(bus.history(from_agent="x")) == 2


# ─── Shared evidence + context ───────────────────────────────


def test_shared_evidence_store_add_and_query():
    s = SharedEvidenceStore()
    s.add(
        SharedEvidenceItem(
            producer="research",
            kind="citation",
            title="c1",
            consumer="compliance",
        )
    )
    s.add(
        SharedEvidenceItem(
            producer="risk",
            kind="score",
            title="c2",
            consumer="*",
        )
    )
    assert len(s.for_consumer("compliance")) == 2  # consumer=compliance + "*"
    assert len(s.for_consumer("risk")) == 1
    assert len(s.by_producer("research")) == 1


def test_execution_context_manager_snapshot():
    ctx = SharedExecutionContext(actor="alice")
    m = ExecutionContextManager(ctx)
    m.add_evidence(
        SharedEvidenceItem(producer="x", kind="y", title="t")
    )
    m.write_memory("k", "v")
    snap = m.snapshot()
    assert snap["actor"] == "alice"
    assert "k" in snap["memory_keys"]
    assert len(snap["evidence_keys"]) == 1


# ─── Routing / policy ─────────────────────────────────────────


def test_capability_based_router_returns_all_when_no_match():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    cand = r.candidates_for(
        AgentExecutionStep(agent_name="*", capability="unknown")
    )
    assert len(cand) == 2


def test_capability_based_router_filters_by_agent_name():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    cand = r.candidates_for(
        AgentExecutionStep(agent_name="a", capability="x")
    )
    assert len(cand) == 1
    assert cand[0].name == "a"


def test_selection_policy_prefers_named_agent():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    p = AgentSelectionPolicy(prefer_healthy=True)
    step = AgentExecutionStep(agent_name="b", capability="x")
    chosen = p.select(step, r.candidates_for(step))
    assert chosen.name == "b"


# ─── Conflict / consensus / aggregation ──────────────────────


def test_conflict_resolver_picks_highest_confidence():
    winner, conflicts = ConflictResolver.resolve(
        [("a", 0.5), ("b", 0.9), ("c", 0.7)]
    )
    assert winner == "b"
    assert conflicts == 2


def test_conflict_resolver_empty():
    winner, conflicts = ConflictResolver.resolve([])
    assert winner is None and conflicts == 0


def test_consensus_builder_full_agreement():
    score = ConsensusBuilder.score(
        [("yes", 0.8), ("yes", 0.7), ("yes", 0.9)]
    )
    assert score == 1.0


def test_consensus_builder_partial_agreement():
    score = ConsensusBuilder.score(
        [("yes", 0.8), ("no", 0.7), ("yes", 0.9)]
    )
    assert 0.0 < score < 1.0


def test_evidence_aggregator_dedupes_by_id():
    a = SharedEvidenceItem(
        evidence_id="e1", producer="a", kind="x", title="t"
    )
    b = SharedEvidenceItem(
        evidence_id="e1", producer="b", kind="x", title="t"
    )
    c = SharedEvidenceItem(
        evidence_id="e2", producer="a", kind="x", title="t"
    )
    merged = EvidenceAggregator.merge(
        {"a": [a, c], "b": [b]}
    )
    assert len(merged) == 2
    assert {m.evidence_id for m in merged} == {"e1", "e2"}


# ─── Result synthesizer ───────────────────────────────────────


def test_result_synthesizer_empty():
    s = ResultSynthesizer()
    out, conf, cons, conflicts = s.synthesize(
        "q", [], []
    )
    assert out["summary"].startswith("no agent")
    assert conf == 0.0


def test_result_synthesizer_weighted_confidence():
    s = ResultSynthesizer()
    contribs = [
        type(
            "C",
            (),
            {
                "agent_name": "a",
                "status": "succeeded",
                "summary": "ok",
                "output": {"k": "v"},
                "confidence": 0.8,
            },
        )(),
        type(
            "C",
            (),
            {
                "agent_name": "b",
                "status": "succeeded",
                "summary": "ok",
                "output": {"k": "v"},
                "confidence": 0.4,
            },
        )(),
    ]
    out, conf, cons, conflicts = s.synthesize("q", contribs, [])
    assert 0.4 < conf < 0.8
    assert out["primary_summary"] == "ok"
    assert out["agent_count"] == 2


# ─── Coordinator + engine ────────────────────────────────────


@pytest.mark.asyncio
async def test_task_coordinator_dispatch_picks_agent():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    coord = TaskCoordinator(
        framework_service=framework, router=r
    )
    step = AgentExecutionStep(agent_name="a", capability="x")
    agent, _ = await coord.dispatch(
        step, "q", SharedExecutionContext()
    )
    assert agent.name == "a"


@pytest.mark.asyncio
async def test_orchestration_engine_runs_sequential():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    graph = AgentExecutionGraph(
        steps=[
            AgentExecutionStep(
                agent_name="a", capability="x", depends_on=[]
            ),
            AgentExecutionStep(
                agent_name="b",
                capability="x",
                depends_on=[],
            ),
        ],
        mode=ExecutionMode.SEQUENTIAL,
    )
    contribs: list = []
    await engine.run_graph(
        graph, "q", SharedExecutionContext(), contributions=contribs
    )
    assert len(contribs) == 2


@pytest.mark.asyncio
async def test_orchestration_engine_handles_missing_agent():
    framework = _StubFramework([])
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    graph = AgentExecutionGraph(
        steps=[
            AgentExecutionStep(
                agent_name="missing", capability="x", depends_on=[]
            )
        ]
    )
    contribs: list = []
    await engine.run_graph(
        graph, "q", SharedExecutionContext(), contributions=contribs
    )
    assert len(contribs) == 1
    assert contribs[0].status == "failed"


# ─── Workflow manager ────────────────────────────────────────


def test_agent_workflow_manager_register_and_run_lookup():
    wm = AgentWorkflowManager()
    d = WorkflowDefinition(
        name="t",
        graph=AgentExecutionGraph(
            steps=[AgentExecutionStep(agent_name="x", capability="x")]
        ),
    )
    wm.register(d)
    assert wm.get(d.workflow_id) is not None
    run = AgentWorkflow(
        workflow_id=d.workflow_id, workflow_name=d.name
    )
    wm.record_run(run)
    assert wm.get_run(run.run_id) is not None
    assert len(wm.list_definitions()) == 1
    assert len(wm.list_runs(limit=10)) == 1


# ─── Orchestrator + service end-to-end ───────────────────────


@pytest.mark.asyncio
async def test_orchestrator_runs_sequential_pipeline():
    agents = [
        _StubAgent(
            "research-agent",
            output={"summary": "r1", "confidence": 0.7},
        ),
        _StubAgent(
            "compliance-agent",
            output={"summary": "c1", "confidence": 0.8},
        ),
        _StubAgent(
            "risk-agent",
            output={"summary": "rk1", "confidence": 0.6},
        ),
        _StubAgent(
            "audit-agent",
            output={"summary": "a1", "confidence": 0.9},
        ),
    ]
    framework = _StubFramework(agents)
    bus = AgentMessageBus()
    evidence = SharedEvidenceStore()
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=bus,
        evidence_store=evidence,
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=AgentWorkflowManager(),
    )
    req = OrchestrationRequest(
        query="KYC compliance check",
        desired_agents=[
            "research-agent",
            "compliance-agent",
            "risk-agent",
            "audit-agent",
        ],
        mode=ExecutionMode.SEQUENTIAL,
    )
    res = await orch.orchestrate(req)
    assert res.status == WorkflowStatus.SUCCEEDED
    assert len(res.contributions) == 4
    assert res.final_confidence > 0.5
    assert len(res.messages) >= 1
    assert len(res.shared_evidence) == 4


@pytest.mark.asyncio
async def test_orchestrator_handles_partial_failure():
    agents = [
        _StubAgent("research-agent"),
        _FailingAgent("compliance-agent"),
    ]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=AgentMessageBus(),
        evidence_store=SharedEvidenceStore(),
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=AgentWorkflowManager(),
    )
    req = OrchestrationRequest(
        query="kYc check",
        desired_agents=["research-agent", "compliance-agent"],
    )
    res = await orch.orchestrate(req)
    assert res.status == WorkflowStatus.PARTIALLY_SUCCEEDED


@pytest.mark.asyncio
async def test_orchestrator_handles_all_failure():
    agents = [_FailingAgent("a"), _FailingAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=AgentMessageBus(),
        evidence_store=SharedEvidenceStore(),
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=AgentWorkflowManager(),
    )
    req = OrchestrationRequest(
        query="kYc check",
        desired_agents=["a", "b"],
    )
    res = await orch.orchestrate(req)
    assert res.status == WorkflowStatus.FAILED


@pytest.mark.asyncio
async def test_orchestrator_runs_parallel():
    agents = [
        _StubAgent("a"),
        _StubAgent("b"),
    ]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=AgentMessageBus(),
        evidence_store=SharedEvidenceStore(),
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=AgentWorkflowManager(),
    )
    req = OrchestrationRequest(
        query="kYc check",
        desired_agents=["a", "b"],
        mode=ExecutionMode.PARALLEL,
    )
    res = await orch.orchestrate(req)
    assert res.status == WorkflowStatus.SUCCEEDED
    assert res.mode == ExecutionMode.PARALLEL


@pytest.mark.asyncio
async def test_orchestrator_runs_with_custom_graph():
    agents = [_StubAgent("x"), _StubAgent("y")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=AgentMessageBus(),
        evidence_store=SharedEvidenceStore(),
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=AgentWorkflowManager(),
    )
    graph = AgentExecutionGraph(
        steps=[
            AgentExecutionStep(agent_name="x", capability="a"),
            AgentExecutionStep(
                agent_name="y", capability="a", depends_on=[]
            ),
        ]
    )
    req = OrchestrationRequest(query="kYc check", graph=graph)
    res = await orch.orchestrate(req)
    assert len(res.contributions) == 2


@pytest.mark.asyncio
async def test_orchestrator_runs_workflow():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    r = CapabilityBasedRouter(framework)
    engine = OrchestrationEngine(
        framework_service=framework,
        coordinator=TaskCoordinator(
            framework_service=framework, router=r
        ),
    )
    wm = AgentWorkflowManager()
    orch = AgentOrchestrator(
        framework_service=framework,
        bus=AgentMessageBus(),
        evidence_store=SharedEvidenceStore(),
        engine=engine,
        synthesizer=ResultSynthesizer(),
        workflow_manager=wm,
    )
    d = WorkflowDefinition(
        name="t",
        graph=AgentExecutionGraph(
            steps=[
                AgentExecutionStep(agent_name="a", capability="x"),
                AgentExecutionStep(agent_name="b", capability="x"),
            ]
        ),
    )
    run = await orch.run_workflow(d, query="run the workflow")
    assert run.status == WorkflowStatus.SUCCEEDED
    assert run.result is not None
    assert wm.get_run(run.run_id) is run


# ─── Service facade ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_orchestration_service_metrics_update():
    agents = [_StubAgent("a"), _StubAgent("b")]
    framework = _StubFramework(agents)
    svc = build_default_orchestration_service(
        framework_service=framework
    )
    req = OrchestrationRequest(
        query="kYc check",
        desired_agents=["a", "b"],
    )
    res = await svc.orchestrate(req)
    assert res.status == WorkflowStatus.SUCCEEDED
    m = svc.metrics()
    assert m.total_executions == 1
    assert m.total_successful == 1
    assert m.average_confidence > 0


def test_orchestration_service_lists_workflows_empty():
    agents: list = []
    framework = _StubFramework(agents)
    svc = build_default_orchestration_service(
        framework_service=framework
    )
    assert svc.list_workflows() == []
    assert svc.list_runs(limit=10) == []


# ─── API integration ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_api_orchestrate():
    from app.api.dependencies import (
        get_orchestration_service,
        reset_orchestration_service,
    )
    reset_orchestration_service()
    agents = [
        _StubAgent("research-agent"),
        _StubAgent("compliance-agent"),
    ]
    framework = _StubFramework(agents)
    svc = build_default_orchestration_service(
        framework_service=framework
    )
    app.dependency_overrides[
        get_orchestration_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.post(
                "/api/v1/agents/orchestrate",
                json={
                    "query": "kyc compliance check",
                    "desired_agents": [
                        "research-agent",
                        "compliance-agent",
                    ],
                    "mode": "sequential",
                },
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["status"] == "succeeded"
            assert len(body["agents_used"]) == 2
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_workflow_register_and_run():
    from app.api.dependencies import (
        get_orchestration_service,
        reset_orchestration_service,
    )
    reset_orchestration_service()
    agents = [_StubAgent("a")]
    framework = _StubFramework(agents)
    svc = build_default_orchestration_service(
        framework_service=framework
    )
    app.dependency_overrides[
        get_orchestration_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.post(
                "/api/v1/agents/workflows",
                json={
                    "name": "test-wf",
                    "graph": {
                        "steps": [
                            {
                                "agent_name": "a",
                                "capability": "x",
                                "depends_on": [],
                            }
                        ],
                        "mode": "sequential",
                    },
                },
            )
            assert r.status_code == 200, r.text
            wf_id = r.json()["workflow_id"]
            r2 = await ac.post(
                f"/api/v1/agents/workflows/{wf_id}/run",
                json={"query": "start the workflow"},
            )
            assert r2.status_code == 200
            assert r2.json()["status"] == "succeeded"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_api_orchestration_health_and_metrics():
    from app.api.dependencies import (
        get_orchestration_service,
        reset_orchestration_service,
    )
    reset_orchestration_service()
    svc = build_default_orchestration_service(
        framework_service=_StubFramework([])
    )
    app.dependency_overrides[
        get_orchestration_service
    ] = lambda: svc
    try:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as ac:
            r = await ac.get(
                "/api/v1/agents/orchestration/health"
            )
            assert r.status_code == 200
            assert r.json()["status"] == "healthy"
            r2 = await ac.get(
                "/api/v1/agents/orchestration/metrics"
            )
            assert r2.status_code == 200
            assert "total_executions" in r2.json()
            r3 = await ac.get("/api/v1/agents/messages")
            assert r3.status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_running_mean_helper():
    from app.services.orchestration import _running_mean
    assert _running_mean(0.0, 5.0, 1) == 5.0
    assert _running_mean(5.0, 7.0, 2) == 6.0


def test_message_bus_subscriber_remove():
    bus = AgentMessageBus()
    cb_calls: list = []
    cb = lambda m: cb_calls.append(m)
    bus.subscribe("a", cb)
    bus.unsubscribe("a", cb)
    bus.publish(
        AgentMessage(
            from_agent="x", to_agent="a", kind=MessageKind.TASK
        )
    )
    assert cb_calls == []
