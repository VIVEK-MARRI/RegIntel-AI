"""Tests for Module 9 — Multi-Agent Framework."""

from __future__ import annotations

import asyncio
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.agents import (
    AgentCapability,
    AgentContext,
    AgentExecutionRequest,
    AgentMetadata,
    AgentRegistrationRequest,
    AgentTask,
    AgentResult,
    CapabilityKind,
    CoordinatorPlan,
    CoordinatorRequest,
    TaskStatus,
)
from app.services.agents import (
    AgentDiscoveryService,
    AgentExecutionEngine,
    AgentFrameworkService,
    AgentMetadataStore,
    AgentRegistry,
    BaseAgent,
    CapabilityAgent,
    CapabilityRegistry,
    CoordinatorAgent,
    EchoAgent,
    ResultAggregator,
    TaskDistributor,
    TaskPlanner,
)


# ─── Service-level fixtures ────────────────────────────────


@pytest.fixture
def store() -> AgentMetadataStore:
    return AgentMetadataStore()


@pytest.fixture
def service(store: AgentMetadataStore) -> AgentFrameworkService:
    return AgentFrameworkService(store)


# ─── BaseAgent lifecycle ─────────────────────────────────


class TestBaseAgentLifecycle:
    def test_start_activates_agent(self) -> None:
        a = EchoAgent(
            AgentMetadata(
                name="t",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.OTHER, name="t"
                    )
                ],
            )
        )
        assert a.status.value == "registered"
        a.start()
        assert a.status.value == "active"

    def test_pause_and_disable(self) -> None:
        a = EchoAgent(AgentMetadata(name="t"))
        a.pause()
        assert a.status.value == "paused"
        a.disable()
        assert a.status.value == "disabled"

    def test_supports_capability(self) -> None:
        a = EchoAgent(
            AgentMetadata(
                name="t",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            )
        )
        assert a.supports(CapabilityKind.RETRIEVAL)
        assert not a.supports(CapabilityKind.REASONING)

    def test_health_initial(self) -> None:
        a = EchoAgent(AgentMetadata(name="t"))
        h = a.health()
        assert h.healthy is True
        assert h.total_invocations == 0


# ─── EchoAgent + engine ───────────────────────────────────


class TestEchoAgent:
    @pytest.mark.asyncio
    async def test_echo(self) -> None:
        a = EchoAgent(AgentMetadata(name="t"))
        task = AgentTask(
            capability=CapabilityKind.OTHER,
            input={"msg": "hello"},
        )
        result = await a.execute(task)
        assert result.status == TaskStatus.SUCCEEDED
        assert result.output["echo"] == {"msg": "hello"}


class TestExecutionEngine:
    @pytest.mark.asyncio
    async def test_run_succeeds(self) -> None:
        a = EchoAgent(
            AgentMetadata(name="t", default_timeout_ms=5000)
        )
        engine = AgentExecutionEngine()
        result = await engine.run(
            a,
            AgentTask(
                capability=CapabilityKind.OTHER, input={"x": 1}
            ),
        )
        assert result.succeeded
        assert result.attempts == 1
        assert result.duration_ms >= 0

    @pytest.mark.asyncio
    async def test_run_times_out(self) -> None:
        class SlowAgent(BaseAgent):
            async def execute(self, task: AgentTask) -> AgentResult:
                await asyncio.sleep(0.5)
                return AgentResult(
                    task_id=task.task_id, status=TaskStatus.SUCCEEDED
                )

        a = SlowAgent(
            AgentMetadata(name="slow", default_timeout_ms=200)
        )
        engine = AgentExecutionEngine()
        result = await engine.run(
            a,
            AgentTask(
                capability=CapabilityKind.OTHER, timeout_ms=100
            ),
        )
        assert result.status == TaskStatus.TIMED_OUT

    @pytest.mark.asyncio
    async def test_run_retries_on_failure(self) -> None:
        attempts = {"n": 0}

        class FlakyAgent(BaseAgent):
            async def execute(self, task: AgentTask) -> AgentResult:
                attempts["n"] += 1
                if attempts["n"] < 2:
                    raise RuntimeError("boom")
                return AgentResult(
                    task_id=task.task_id,
                    status=TaskStatus.SUCCEEDED,
                    output={"ok": True},
                )

        a = FlakyAgent(
            AgentMetadata(name="flaky", default_max_retries=2)
        )
        engine = AgentExecutionEngine()
        result = await engine.run(
            a, AgentTask(capability=CapabilityKind.OTHER)
        )
        assert result.succeeded
        assert result.attempts == 2
        assert attempts["n"] == 2

    @pytest.mark.asyncio
    async def test_run_exhausts_retries(self) -> None:
        class AlwaysFails(BaseAgent):
            async def execute(self, task: AgentTask) -> AgentResult:
                raise RuntimeError("always")

        a = AlwaysFails(AgentMetadata(name="f", default_max_retries=1))
        engine = AgentExecutionEngine()
        result = await engine.run(
            a, AgentTask(capability=CapabilityKind.OTHER)
        )
        assert result.status == TaskStatus.FAILED
        assert "always" in result.error


# ─── CapabilityAgent ──────────────────────────────────────


class TestCapabilityAgent:
    @pytest.mark.asyncio
    async def test_handler_returns_dict(self) -> None:
        a = CapabilityAgent(
            AgentMetadata(
                name="cap",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            handler=lambda t: {"got": t.input},
        )
        r = await a.execute(
            AgentTask(
                capability=CapabilityKind.RETRIEVAL, input={"q": "x"}
            )
        )
        assert r.output == {"got": {"q": "x"}}

    @pytest.mark.asyncio
    async def test_async_handler(self) -> None:
        async def handler(t):
            return {"async": True, "input": t.input}

        a = CapabilityAgent(
            AgentMetadata(name="cap2"),
            handler=handler,
        )
        r = await a.execute(
            AgentTask(capability=CapabilityKind.OTHER, input={"a": 1})
        )
        assert r.output == {"async": True, "input": {"a": 1}}

    @pytest.mark.asyncio
    async def test_handler_returns_result(self) -> None:
        a = CapabilityAgent(
            AgentMetadata(name="cap3"),
            handler=lambda t: AgentResult(
                task_id=t.task_id,
                status=TaskStatus.SUCCEEDED,
                output={"preset": True},
            ),
        )
        r = await a.execute(AgentTask(capability=CapabilityKind.OTHER))
        assert r.output == {"preset": True}


# ─── Registry ─────────────────────────────────────────────


class TestAgentRegistry:
    def test_register_and_lookup(self, service: AgentFrameworkService) -> None:
        a = EchoAgent(AgentMetadata(name="a"))
        meta = service.register(
            AgentRegistrationRequest(
                name="a",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.OTHER, name="o"
                    )
                ],
            ),
            a,
        )
        assert service.get_agent("a").agent_id == meta.agent_id
        assert service.get_agent_instance("a") is a

    def test_unregister(self, service: AgentFrameworkService) -> None:
        a = EchoAgent(AgentMetadata(name="a"))
        service.register(
            AgentRegistrationRequest(name="a"), a
        )
        assert service.unregister("a") is True
        assert service.unregister("a") is False

    def test_list_agents(
        self, service: AgentFrameworkService
    ) -> None:
        # Echo agent is seeded
        names = [m.name for m in service.list_agents()]
        assert "echo-agent" in names


# ─── CapabilityRegistry ──────────────────────────────────


class TestCapabilityRegistry:
    def test_by_capability(
        self, service: AgentFrameworkService
    ) -> None:
        a = EchoAgent(AgentMetadata(name="r1"))
        service.register(
            AgentRegistrationRequest(
                name="r1",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            a,
        )
        a2 = EchoAgent(AgentMetadata(name="r2"))
        service.register(
            AgentRegistrationRequest(
                name="r2",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r",
                        parameters={"lang": "en"},
                    )
                ],
                priority=10,
            ),
            a2,
        )
        matches = service.capability_registry.by_capability(
            CapabilityKind.RETRIEVAL
        )
        # r2 should be first because of higher priority
        assert matches[0].name == "r2"

    def test_best_match(self, service: AgentFrameworkService) -> None:
        a = EchoAgent(AgentMetadata(name="b"))
        service.register(
            AgentRegistrationRequest(
                name="b",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.REASONING, name="r"
                    )
                ],
            ),
            a,
        )
        best = service.capability_registry.best_match(
            CapabilityKind.REASONING
        )
        assert best is not None
        assert best.name == "b"

    def test_no_match(self, service: AgentFrameworkService) -> None:
        assert (
            service.capability_registry.best_match(
                CapabilityKind.AUDIT
            )
            is None
        )


# ─── Discovery ────────────────────────────────────────────


class TestAgentDiscovery:
    def test_search_by_capability(
        self, service: AgentFrameworkService
    ) -> None:
        service.register(
            AgentRegistrationRequest(
                name="r1",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            EchoAgent(AgentMetadata(name="r1")),
        )
        from app.schemas.agents import AgentDiscoveryQuery

        result = service.search_agents(
            AgentDiscoveryQuery(
                capability=CapabilityKind.RETRIEVAL
            )
        )
        assert result.total >= 1
        assert any(i.name == "r1" for i in result.items)

    def test_search_by_text(
        self, service: AgentFrameworkService
    ) -> None:
        service.register(
            AgentRegistrationRequest(
                name="rbi-monitor",
                description="Monitors RBI circulars",
            ),
            EchoAgent(AgentMetadata(name="rbi-monitor")),
        )
        from app.schemas.agents import AgentDiscoveryQuery

        result = service.search_agents(
            AgentDiscoveryQuery(text_query="rbi")
        )
        assert any(i.name == "rbi-monitor" for i in result.items)

    def test_search_healthy_only(
        self, service: AgentFrameworkService
    ) -> None:
        a = EchoAgent(AgentMetadata(name="h"))
        service.register(
            AgentRegistrationRequest(name="h"), a
        )
        # Force 5 consecutive failures
        for _ in range(5):
            a._record_failure("err", 0.0)
        from app.schemas.agents import AgentDiscoveryQuery

        result = service.search_agents(
            AgentDiscoveryQuery(healthy_only=True)
        )
        assert not any(i.name == "h" for i in result.items)


# ─── Health ───────────────────────────────────────────────


class TestAgentHealth:
    @pytest.mark.asyncio
    async def test_health_after_run(
        self, service: AgentFrameworkService
    ) -> None:
        a = EchoAgent(AgentMetadata(name="x"))
        service.register(
            AgentRegistrationRequest(name="x"), a
        )
        engine = AgentExecutionEngine()
        await engine.run(
            a, AgentTask(capability=CapabilityKind.OTHER)
        )
        h = service.health("x")
        assert h.total_invocations == 1
        assert h.successful_invocations == 1
        assert h.last_success_at is not None

    def test_health_unknown(
        self, service: AgentFrameworkService
    ) -> None:
        assert service.health("missing") is None


# ─── TaskPlanner ──────────────────────────────────────────


class TestTaskPlanner:
    def test_plan_with_explicit_caps(self) -> None:
        p = TaskPlanner()
        plan = p.plan(
            CoordinatorRequest(
                query="hello",
                desired_capabilities=[
                    CapabilityKind.RETRIEVAL,
                    CapabilityKind.REASONING,
                ],
            )
        )
        assert len(plan.steps) == 2
        assert plan.steps[0].capability == CapabilityKind.RETRIEVAL
        assert plan.steps[1].capability == CapabilityKind.REASONING

    def test_infer_capabilities(self) -> None:
        p = TaskPlanner()
        plan = p.plan(
            CoordinatorRequest(query="please forecast the risk")
        )
        kinds = [s.capability for s in plan.steps]
        assert CapabilityKind.FORECASTING in kinds

    def test_max_steps(self) -> None:
        p = TaskPlanner()
        plan = p.plan(
            CoordinatorRequest(
                query="analyze",
                desired_capabilities=[
                    CapabilityKind.RETRIEVAL,
                    CapabilityKind.REASONING,
                    CapabilityKind.SUMMARIZATION,
                    CapabilityKind.RISK_ASSESSMENT,
                ],
                max_steps=2,
            )
        )
        assert len(plan.steps) == 2


# ─── TaskDistributor ──────────────────────────────────────


class TestTaskDistributor:
    def test_distribute(
        self, service: AgentFrameworkService
    ) -> None:
        service.register(
            AgentRegistrationRequest(
                name="r1",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            EchoAgent(AgentMetadata(name="r1")),
        )
        p = TaskPlanner()
        plan = p.plan(
            CoordinatorRequest(
                query="search",
                desired_capabilities=[CapabilityKind.RETRIEVAL],
            )
        )
        d = TaskDistributor(service.discovery)
        tasks = d.distribute(plan, AgentContext())
        assert len(tasks) == 1
        assert tasks[0].target_agent == "r1"
        assert "r1" in plan.selected_agents

    def test_distribute_no_agent(
        self, service: AgentFrameworkService
    ) -> None:
        p = TaskPlanner()
        plan = p.plan(
            CoordinatorRequest(
                query="audit",
                desired_capabilities=[CapabilityKind.AUDIT],
            )
        )
        d = TaskDistributor(service.discovery)
        tasks = d.distribute(plan, AgentContext())
        assert tasks[0].target_agent == ""


# ─── ResultAggregator ─────────────────────────────────────


class TestResultAggregator:
    def test_aggregate_all_success(self) -> None:
        agg = ResultAggregator()
        plan = CoordinatorPlan(
            query="q",
            steps=[],
            selected_agents=["a"],
        )
        r1 = AgentResult(
            agent_name="a",
            status=TaskStatus.SUCCEEDED,
            output={"x": 1},
        )
        r2 = AgentResult(
            agent_name="b",
            status=TaskStatus.SUCCEEDED,
            output={"y": 2},
        )
        final = agg.aggregate(plan, [r1, r2])
        assert final.status == TaskStatus.SUCCEEDED
        assert final.final_output["successful_count"] == 2
        assert final.final_output["failed_count"] == 0
        assert "primary_output" not in final.final_output

    def test_aggregate_one_success(self) -> None:
        agg = ResultAggregator()
        plan = CoordinatorPlan(query="q", steps=[], selected_agents=[])
        r = AgentResult(
            agent_name="a",
            status=TaskStatus.SUCCEEDED,
            output={"only": True},
        )
        final = agg.aggregate(plan, [r])
        assert final.final_output["primary_output"] == {"only": True}

    def test_aggregate_mixed(self) -> None:
        agg = ResultAggregator()
        plan = CoordinatorPlan(query="q", steps=[], selected_agents=[])
        r1 = AgentResult(
            agent_name="a",
            status=TaskStatus.SUCCEEDED,
            output={"x": 1},
        )
        r2 = AgentResult(
            agent_name="b",
            status=TaskStatus.FAILED,
            error="boom",
        )
        final = agg.aggregate(plan, [r1, r2])
        assert final.status == TaskStatus.SUCCEEDED
        assert final.final_output["failed_count"] == 1
        assert final.notes != ""


# ─── Coordinator ──────────────────────────────────────────


class TestCoordinator:
    @pytest.mark.asyncio
    async def test_coordinate_with_echo(
        self, service: AgentFrameworkService
    ) -> None:
        result = await service.coordinate(
            CoordinatorRequest(
                query="search and reason",
                desired_capabilities=[
                    CapabilityKind.RETRIEVAL,
                    CapabilityKind.REASONING,
                ],
            )
        )
        # Echo agent only supports OTHER, so the steps should fail
        # to find an agent but the coordinator should still complete
        assert result.plan_id
        assert result.status == TaskStatus.FAILED
        assert len(result.step_results) == 2

    @pytest.mark.asyncio
    async def test_coordinate_uses_registered_agent(
        self, service: AgentFrameworkService
    ) -> None:
        # Register an agent that supports RETRIEVAL
        a = EchoAgent(AgentMetadata(name="r"))
        service.register(
            AgentRegistrationRequest(
                name="r",
                capabilities=[
                    AgentCapability(
                        kind=CapabilityKind.RETRIEVAL, name="r"
                    )
                ],
            ),
            a,
        )
        result = await service.coordinate(
            CoordinatorRequest(
                query="search",
                desired_capabilities=[CapabilityKind.RETRIEVAL],
            )
        )
        assert result.status == TaskStatus.SUCCEEDED
        assert "r" in result.selected_agents

    @pytest.mark.asyncio
    async def test_coordinate_with_inferred_caps(
        self, service: AgentFrameworkService
    ) -> None:
        # Register retrieval, reasoning, forecasting agents
        for cap in (
            CapabilityKind.RETRIEVAL,
            CapabilityKind.REASONING,
            CapabilityKind.FORECASTING,
        ):
            a = EchoAgent(
                AgentMetadata(
                    name=f"a-{cap.value}",
                    capabilities=[
                        AgentCapability(kind=cap, name=cap.value)
                    ],
                )
            )
            service.register(
                AgentRegistrationRequest(
                    name=f"a-{cap.value}",
                    capabilities=[
                        AgentCapability(kind=cap, name=cap.value)
                    ],
                ),
                a,
            )
        result = await service.coordinate(
            CoordinatorRequest(query="please retrieve and forecast the trend")
        )
        assert result.status == TaskStatus.SUCCEEDED
        assert len(result.step_results) >= 2


# ─── Service-level: execute ───────────────────────────────


class TestServiceExecute:
    @pytest.mark.asyncio
    async def test_execute_known_agent(
        self, service: AgentFrameworkService
    ) -> None:
        a = EchoAgent(AgentMetadata(name="x"))
        service.register(
            AgentRegistrationRequest(name="x"), a
        )
        r = await service.execute(
            AgentExecutionRequest(
                agent_name="x",
                capability=CapabilityKind.OTHER,
                input={"hi": "there"},
            )
        )
        assert r.succeeded
        assert r.agent_name == "x"

    @pytest.mark.asyncio
    async def test_execute_unknown_agent(
        self, service: AgentFrameworkService
    ) -> None:
        r = await service.execute(
            AgentExecutionRequest(
                agent_name="nope",
                capability=CapabilityKind.OTHER,
            )
        )
        assert r.status == TaskStatus.FAILED
        assert "not found" in r.error


# ─── Service-level: health tracking ───────────────────────


class TestServiceHealthTracking:
    @pytest.mark.asyncio
    async def test_health_increments_after_execution(
        self, service: AgentFrameworkService
    ) -> None:
        a = EchoAgent(AgentMetadata(name="h"))
        service.register(
            AgentRegistrationRequest(name="h"), a
        )
        await service.execute(
            AgentExecutionRequest(
                agent_name="h",
                capability=CapabilityKind.OTHER,
            )
        )
        h = service.health("h")
        assert h.total_invocations == 1
        assert h.successful_invocations == 1


# ─── API tests ────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport, base_url="http://test"
    ) as ac:
        yield ac


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/agents/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "metrics" in body


@pytest.mark.asyncio
async def test_api_list_agents(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/agents/agents")
    assert r.status_code == 200
    items = r.json()["items"]
    # Echo agent is seeded
    assert any(i["name"] == "echo-agent" for i in items)


@pytest.mark.asyncio
async def test_api_register_and_unregister(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/agents/agents",
        json={
            "name": "test-agent",
            "description": "test",
            "capabilities": [
                {"kind": "retrieval", "name": "r"}
            ],
            "tags": ["test"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["name"] == "test-agent"
    r2 = await client.get("/api/v1/agents/agents/test-agent")
    assert r2.status_code == 200
    r3 = await client.delete("/api/v1/agents/agents/test-agent")
    assert r3.status_code == 200
    r4 = await client.get("/api/v1/agents/agents/test-agent")
    assert r4.status_code == 404


@pytest.mark.asyncio
async def test_api_register_unknown_404(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/agents/agents/missing")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_api_execute(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/agents/execute",
        json={
            "agent_name": "echo-agent",
            "capability": "other",
            "input": {"hello": "world"},
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "succeeded"
    assert body["output"]["echo"] == {"hello": "world"}


@pytest.mark.asyncio
async def test_api_execute_unknown(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/agents/execute",
        json={
            "agent_name": "missing",
            "capability": "other",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "failed"


@pytest.mark.asyncio
async def test_api_coordinate(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/agents/coordinate",
        json={
            "query": "please retrieve and reason",
            "desired_capabilities": [
                "retrieval",
                "reasoning",
            ],
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert "plan_id" in body
    assert "step_results" in body
    assert len(body["step_results"]) == 2


@pytest.mark.asyncio
async def test_api_search(
    client: AsyncClient,
) -> None:
    r = await client.get(
        "/api/v1/agents/agents?capability=other"
    )
    assert r.status_code == 200
    items = r.json()["items"]
    assert any(i["name"] == "echo-agent" for i in items)


@pytest.mark.asyncio
async def test_api_health_for_agent(
    client: AsyncClient,
) -> None:
    r = await client.get(
        "/api/v1/agents/agents/echo-agent/health"
    )
    assert r.status_code == 200
    body = r.json()
    assert "healthy" in body
    assert body["agent_id"] != ""


@pytest.mark.asyncio
async def test_api_health_for_missing_agent(
    client: AsyncClient,
) -> None:
    r = await client.get(
        "/api/v1/agents/agents/missing/health"
    )
    assert r.status_code == 404
