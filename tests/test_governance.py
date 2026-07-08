"""Tests for Module 8.6 — AI Governance Layer."""

from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport

from app.main import app
from app.schemas.governance import (
    ApprovalPolicyCreateRequest,
    DecisionRegistryFilter,
    DecisionType,
    GovernanceDecisionCreateRequest,
    GovernancePolicyCreateRequest,
    PolicyAction,
    PolicyRule,
    PolicyRuleKind,
    PolicyScope,
    PolicySeverity,
)
from app.services.governance import (
    GovernanceEngine,
    GovernanceService,
    InMemoryGovernanceStore,
    build_default_governance_service,
)


# ─── Service-level fixtures ────────────────────────────────────


@pytest.fixture
def store() -> InMemoryGovernanceStore:
    return InMemoryGovernanceStore()


@pytest.fixture
def service(store: InMemoryGovernanceStore) -> GovernanceService:
    return GovernanceService(store)


@pytest.fixture
def engine() -> GovernanceEngine:
    return GovernanceEngine()


# ─── Engine: rule evaluators ──────────────────────────────────


class TestGovernanceEngine:
    def test_empty_policies_is_compliant(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision

        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            confidence=0.5,
        )
        result = engine.check(d, policies=[])
        assert result.policy_compliant is True
        assert result.violations == []
        assert result.evaluated_rules == 0

    def test_confidence_threshold_below_blocks(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="conf",
            rules=[
                PolicyRule(
                    name="min70",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.BLOCK,
                    parameters={"min_confidence": 0.7},
                )
            ],
        )
        d = GovernanceDecision(decision_type=DecisionType.ANSWER, confidence=0.3)
        r = engine.check(d, policies=[policy])
        assert r.policy_compliant is False
        assert len(r.violations) == 1
        assert r.violations[0].action == PolicyAction.BLOCK
        assert r.has_blocking_violation is True

    def test_confidence_threshold_above_passes(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="conf",
            rules=[
                PolicyRule(
                    name="min70",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.BLOCK,
                    parameters={"min_confidence": 0.7},
                )
            ],
        )
        d = GovernanceDecision(decision_type=DecisionType.ANSWER, confidence=0.95)
        r = engine.check(d, policies=[policy])
        assert r.policy_compliant is True

    def test_human_in_loop_without_approver_violates(
        self, engine: GovernanceEngine
    ) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="hil",
            rules=[
                PolicyRule(
                    name="hil-all",
                    kind=PolicyRuleKind.HUMAN_IN_LOOP,
                    action=PolicyAction.REQUIRE_HUMAN_REVIEW,
                    parameters={"categories": []},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.RISK_ASSESSMENT, confidence=0.9
        )
        r = engine.check(d, policies=[policy])
        assert r.policy_compliant is True  # REQUIRE_HUMAN_REVIEW is not BLOCK
        assert len(r.violations) == 1
        assert not r.has_blocking_violation

    def test_approval_required(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="appr",
            rules=[
                PolicyRule(
                    name="need2",
                    kind=PolicyRuleKind.APPROVAL_REQUIRED,
                    action=PolicyAction.BLOCK,
                    parameters={"min_approvers": 2},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            confidence=0.9,
            approved_by=["alice"],
        )
        r = engine.check(d, policies=[policy])
        assert r.policy_compliant is False

    def test_model_blacklist(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="blk",
            rules=[
                PolicyRule(
                    name="blk-gpt",
                    kind=PolicyRuleKind.MODEL_BLACKLIST,
                    action=PolicyAction.BLOCK,
                    parameters={"blocked_models": ["gpt-3.5-turbo"]},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            model_id="gpt-3.5-turbo",
            confidence=0.9,
        )
        r = engine.check(d, policies=[policy])
        assert r.policy_compliant is False
        assert "blacklisted" in r.violations[0].message

    def test_risk_level_ceiling(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="ceil",
            rules=[
                PolicyRule(
                    name="ceiling-high",
                    kind=PolicyRuleKind.RISK_LEVEL_CEILING,
                    action=PolicyAction.BLOCK,
                    parameters={"max_risk_level": "high"},
                )
            ],
        )
        ok = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            risk_level="medium",
            confidence=0.9,
        )
        bad = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            risk_level="critical",
            confidence=0.9,
        )
        assert engine.check(ok, [policy]).policy_compliant is True
        assert engine.check(bad, [policy]).policy_compliant is False

    def test_category_restriction(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="cat",
            rules=[
                PolicyRule(
                    name="no-pii-cat",
                    kind=PolicyRuleKind.CATEGORY_RESTRICTION,
                    action=PolicyAction.BLOCK,
                    parameters={"blocked_categories": ["pii"]},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            categories=["pii", "aml"],
            confidence=0.9,
        )
        r = engine.check(d, [policy])
        assert r.policy_compliant is False

    def test_pii_prohibition(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="pii",
            rules=[
                PolicyRule(
                    name="no-pii",
                    kind=PolicyRuleKind.PII_PROHIBITION,
                    action=PolicyAction.BLOCK,
                    parameters={},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            confidence=0.9,
            metadata={"contains_pii": True},
        )
        assert engine.check(d, [policy]).policy_compliant is False

    def test_explainability_required(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="exp",
            rules=[
                PolicyRule(
                    name="need-explanation",
                    kind=PolicyRuleKind.EXPLAINABILITY_REQUIRED,
                    action=PolicyAction.BLOCK,
                    parameters={},
                )
            ],
        )
        d = GovernanceDecision(
            decision_type=DecisionType.ANSWER,
            confidence=0.9,
            outputs={},
        )
        assert engine.check(d, [policy]).policy_compliant is False

    def test_disabled_rule_is_ignored(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="x",
            rules=[
                PolicyRule(
                    name="disabled",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.BLOCK,
                    enabled=False,
                    parameters={"min_confidence": 0.99},
                )
            ],
        )
        d = GovernanceDecision(decision_type=DecisionType.ANSWER, confidence=0.1)
        assert engine.check(d, [policy]).policy_compliant is True

    def test_disabled_policy_is_ignored(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="x",
            enabled=False,
            rules=[
                PolicyRule(
                    name="blocker",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.BLOCK,
                    parameters={"min_confidence": 0.99},
                )
            ],
        )
        d = GovernanceDecision(decision_type=DecisionType.ANSWER, confidence=0.1)
        assert engine.check(d, [policy]).policy_compliant is True

    def test_required_actions_dedup(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernanceDecision, GovernancePolicy

        policy = GovernancePolicy(
            name="x",
            rules=[
                PolicyRule(
                    name="a",
                    kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    action=PolicyAction.REQUIRE_APPROVAL,
                    parameters={"min_confidence": 0.99},
                ),
                PolicyRule(
                    name="b",
                    kind=PolicyRuleKind.HUMAN_IN_LOOP,
                    action=PolicyAction.REQUIRE_APPROVAL,
                    parameters={"categories": []},
                ),
            ],
        )
        d = GovernanceDecision(decision_type=DecisionType.ANSWER, confidence=0.1)
        r = engine.check(d, [policy])
        # Both rules emit REQUIRE_APPROVAL but the dedup should keep one
        assert r.required_actions.count(PolicyAction.REQUIRE_APPROVAL) == 1

    def test_highest_severity(self, engine: GovernanceEngine) -> None:
        from app.schemas.governance import GovernancePolicy, PolicyCheckResult

        r = PolicyCheckResult()
        assert r.highest_severity == PolicySeverity.INFO
        r.violations = [
            PolicyRule(
                name="x",
                kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                severity=PolicySeverity.CRITICAL,
            )
        ]  # type: ignore[list-item]
        from app.schemas.governance import PolicyViolation

        r.violations = [
            PolicyViolation(
                rule_id="r1",
                rule_name="a",
                policy_id="p1",
                policy_name="p",
                kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                action=PolicyAction.WARN,
                severity=PolicySeverity.HIGH,
                message="h",
            ),
            PolicyViolation(
                rule_id="r2",
                rule_name="b",
                policy_id="p1",
                policy_name="p",
                kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                action=PolicyAction.BLOCK,
                severity=PolicySeverity.CRITICAL,
                message="c",
            ),
        ]
        assert r.highest_severity == PolicySeverity.CRITICAL


# ─── Service: policies ───────────────────────────────────────


class TestPolicyManagement:
    def test_create_and_get(self, service: GovernanceService) -> None:
        p = service.create_policy(
            GovernancePolicyCreateRequest(
                name="X",
                rules=[
                    PolicyRule(
                        name="r",
                        kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    )
                ],
            )
        )
        assert p.name == "X"
        assert service.get_policy(p.policy_id) is not None

    def test_update(self, service: GovernanceService) -> None:
        p = service.create_policy(GovernancePolicyCreateRequest(name="X"))
        upd = service.update_policy(p.policy_id, enabled=False, name="Y")
        assert upd is not None
        assert upd.enabled is False
        assert upd.name == "Y"

    def test_delete(self, service: GovernanceService) -> None:
        p = service.create_policy(GovernancePolicyCreateRequest(name="X"))
        assert service.delete_policy(p.policy_id) is True
        assert service.get_policy(p.policy_id) is None
        assert service.delete_policy("missing") is False

    def test_default_policies_seeded(self, service: GovernanceService) -> None:
        enabled = service.list_policies(enabled_only=True)
        assert len(enabled) >= 3

    def test_approval_policy_matching(self, service: GovernanceService) -> None:
        ap = service.create_approval_policy(
            ApprovalPolicyCreateRequest(
                name="high-risk-approval",
                decision_types=[DecisionType.RISK_ASSESSMENT],
                min_risk_level="high",
                required_roles=["compliance_officer"],
                min_approvers=2,
            )
        )
        from app.schemas.governance import GovernanceDecision

        d = GovernanceDecision(
            decision_type=DecisionType.RISK_ASSESSMENT,
            risk_level="high",
            confidence=0.9,
        )
        matched = service.matching_approval_policies(d)
        assert any(p.policy_id == ap.policy_id for p in matched)
        # Low-risk decision should not match
        d2 = GovernanceDecision(
            decision_type=DecisionType.RISK_ASSESSMENT,
            risk_level="low",
            confidence=0.9,
        )
        assert not service.matching_approval_policies(d2)


# ─── Service: decision registry ─────────────────────────────


class TestDecisionRegistry:
    def test_register_with_policies(self, service: GovernanceService) -> None:
        d = service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.5,
                check_policies=True,
            )
        )
        assert d.policy_result is not None
        assert d.policy_result.policy_compliant is False  # blocked by 0.7 rule

    def test_register_without_policies(self, service: GovernanceService) -> None:
        d = service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.5,
                check_policies=False,
            )
        )
        assert d.policy_result is None

    def test_get_and_search(self, service: GovernanceService) -> None:
        service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.9,
                check_policies=False,
            )
        )
        d2 = service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.RISK_ASSESSMENT,
                confidence=0.9,
                check_policies=False,
            )
        )
        assert service.get_decision(d2.decision_id) is not None
        flt = DecisionRegistryFilter(
            decision_type=DecisionType.RISK_ASSESSMENT,
            page=1,
            page_size=10,
        )
        out = service.search_decisions(flt)
        assert out.total == 1
        assert out.items[0].decision_id == d2.decision_id

    def test_search_filter_by_compliance(self, service: GovernanceService) -> None:
        service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.95,
                check_policies=True,
            )
        )
        service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.1,
                check_policies=True,
            )
        )
        ok = service.search_decisions(
            DecisionRegistryFilter(policy_compliant=True, page=1, page_size=10)
        )
        bad = service.search_decisions(
            DecisionRegistryFilter(policy_compliant=False, page=1, page_size=10)
        )
        assert ok.total >= 1
        assert bad.total >= 1


# ─── Service: stats ──────────────────────────────────────────


class TestGovernanceStats:
    def test_stats_after_activity(self, service: GovernanceService) -> None:
        service.create_policy(
            GovernancePolicyCreateRequest(
                name="X",
                rules=[
                    PolicyRule(
                        name="r",
                        kind=PolicyRuleKind.CONFIDENCE_THRESHOLD,
                    )
                ],
            )
        )
        service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.9,
                check_policies=True,
            )
        )
        service.register_decision(
            GovernanceDecisionCreateRequest(
                decision_type=DecisionType.ANSWER,
                confidence=0.1,
                check_policies=True,
            )
        )
        s = service.stats()
        assert s.total_policies >= 4  # 3 default + 1
        assert s.total_decisions == 2
        assert s.compliant_decisions >= 1
        assert s.non_compliant_decisions >= 1
        assert s.compliance_rate > 0
        assert "answer" in s.by_decision_type

    def test_policy_scope_filtering(self, service: GovernanceService) -> None:
        p = service.create_policy(
            GovernancePolicyCreateRequest(
                name="scoped",
                scope=PolicyScope.MODEL,
                scope_value="gpt-4",
            )
        )
        service.create_policy(GovernancePolicyCreateRequest(name="global"))
        scoped = service.list_policies(scope=PolicyScope.MODEL)
        assert any(x.policy_id == p.policy_id for x in scoped)
        assert all(x.scope == PolicyScope.MODEL for x in scoped)


# ─── API tests ───────────────────────────────────────────────


@pytest_asyncio.fixture
async def client() -> AsyncClient:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_api_health(client: AsyncClient) -> None:
    r = await client.get("/api/v1/governance/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert "metrics" in body


@pytest.mark.asyncio
async def test_api_create_and_get_policy(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/governance/policies",
        json={
            "name": "API test",
            "rules": [
                {
                    "name": "r1",
                    "kind": "confidence_threshold",
                    "action": "warn",
                    "parameters": {"min_confidence": 0.5},
                }
            ],
        },
    )
    assert r.status_code == 201
    policy = r.json()
    pid = policy["policy_id"]
    r2 = await client.get(f"/api/v1/governance/policies/{pid}")
    assert r2.status_code == 200
    assert r2.json()["policy_id"] == pid


@pytest.mark.asyncio
async def test_api_register_decision(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/governance/decisions",
        json={
            "decision_type": "answer",
            "confidence": 0.9,
            "check_policies": True,
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert "decision_id" in body
    assert body["policy_result"] is not None
    assert "policy_compliant" in body["policy_result"]


@pytest.mark.asyncio
async def test_api_register_and_get_decision(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/governance/decisions",
        json={
            "decision_type": "answer",
            "confidence": 0.9,
            "check_policies": False,
        },
    )
    did = r.json()["decision_id"]
    r2 = await client.get(f"/api/v1/governance/decisions/{did}")
    assert r2.status_code == 200
    assert r2.json()["decision_id"] == did


@pytest.mark.asyncio
async def test_api_recheck_decision(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/governance/decisions",
        json={
            "decision_type": "answer",
            "confidence": 0.9,
            "check_policies": False,
        },
    )
    did = r.json()["decision_id"]
    r2 = await client.post(f"/api/v1/governance/decisions/{did}/check")
    assert r2.status_code == 200
    body = r2.json()
    assert "policy_compliant" in body
    assert "violations" in body


@pytest.mark.asyncio
async def test_api_stats(client: AsyncClient) -> None:
    r = await client.get("/api/v1/governance/stats")
    assert r.status_code == 200
    body = r.json()
    assert "total_policies" in body
    assert "compliance_rate" in body


@pytest.mark.asyncio
async def test_api_get_unknown_returns_404(
    client: AsyncClient,
) -> None:
    r = await client.get("/api/v1/governance/policies/does-not-exist")
    assert r.status_code == 404
    r2 = await client.get("/api/v1/governance/decisions/does-not-exist")
    assert r2.status_code == 404


@pytest.mark.asyncio
async def test_api_update_and_delete_policy(
    client: AsyncClient,
) -> None:
    r = await client.post("/api/v1/governance/policies", json={"name": "upd"})
    pid = r.json()["policy_id"]
    r2 = await client.patch(
        f"/api/v1/governance/policies/{pid}?enabled=false&name=renamed"
    )
    assert r2.status_code == 200
    assert r2.json()["enabled"] is False
    assert r2.json()["name"] == "renamed"
    r3 = await client.delete(f"/api/v1/governance/policies/{pid}")
    assert r3.status_code == 204
    r4 = await client.delete(f"/api/v1/governance/policies/{pid}")
    assert r4.status_code == 404


@pytest.mark.asyncio
async def test_api_approval_policies_crud(
    client: AsyncClient,
) -> None:
    r = await client.post(
        "/api/v1/governance/approval-policies",
        json={
            "name": "high-risk-approval",
            "decision_types": ["risk_assessment"],
            "min_risk_level": "high",
            "required_roles": ["compliance_officer"],
            "min_approvers": 2,
        },
    )
    assert r.status_code == 201
    aid = r.json()["policy_id"]
    r2 = await client.get("/api/v1/governance/approval-policies")
    assert r2.status_code == 200
    assert any(p["policy_id"] == aid for p in r2.json())
    r3 = await client.get(f"/api/v1/governance/approval-policies/{aid}")
    assert r3.status_code == 200
    r4 = await client.delete(f"/api/v1/governance/approval-policies/{aid}")
    assert r4.status_code == 204


@pytest.mark.asyncio
async def test_api_list_decisions_pagination(
    client: AsyncClient,
) -> None:
    for i in range(5):
        await client.post(
            "/api/v1/governance/decisions",
            json={
                "decision_type": "answer",
                "confidence": 0.5 + i * 0.05,
                "check_policies": False,
            },
        )
    r = await client.get("/api/v1/governance/decisions?page=1&page_size=2")
    assert r.status_code == 200
    body = r.json()
    assert len(body["items"]) == 2
    assert body["has_more"] is True
