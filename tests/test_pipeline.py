"""Static validation of the M10.4 CI/CD workflows.

These tests load the YAML and check that the jobs, triggers, and pipeline
stages match the M10.4 spec. They do NOT require a real GitHub runner.

Note: PyYAML parses the YAML 1.1 key ``on`` as the boolean ``True`` because
of its loose boolean coercion. We always look it up as ``wf[True]`` to
sidestep that quirk.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml


REPO_ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS_DIR = REPO_ROOT / ".github" / "workflows"
DEPENDABOT = REPO_ROOT / ".github" / "dependabot.yml"


# ─── Helpers ────────────────────────────────────────────────────────

def _load(path: Path) -> Dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _triggers(wf: Dict[str, Any]) -> Dict[str, Any]:
    return wf.get(True, wf.get("on", {}))  # type: ignore[arg-type]


def _dump(obj: Any) -> str:
    """Stable string form of an object for substring checks."""
    import json

    def _coerce(o: Any) -> Any:
        if isinstance(o, dict):
            return {("on" if k is True else k): _coerce(v) for k, v in o.items()}
        if isinstance(o, (list, tuple)):
            return [_coerce(v) for v in o]
        return o

    return json.dumps(_coerce(obj), default=str, sort_keys=True)


@pytest.fixture(scope="module")
def ci() -> Dict[str, Any]:
    return _load(WORKFLOWS_DIR / "ci.yml")


@pytest.fixture(scope="module")
def release() -> Dict[str, Any]:
    return _load(WORKFLOWS_DIR / "release.yml")


@pytest.fixture(scope="module")
def benchmark() -> Dict[str, Any]:
    return _load(WORKFLOWS_DIR / "benchmark.yml")


@pytest.fixture(scope="module")
def dependabot() -> Dict[str, Any]:
    return _load(DEPENDABOT)


# ─── File presence ──────────────────────────────────────────────────

class TestPipelineFiles:
    def test_ci_workflow_exists(self) -> None:
        assert (WORKFLOWS_DIR / "ci.yml").is_file()

    def test_release_workflow_exists(self) -> None:
        assert (WORKFLOWS_DIR / "release.yml").is_file()

    def test_benchmark_workflow_exists(self) -> None:
        assert (WORKFLOWS_DIR / "benchmark.yml").is_file()

    def test_dependabot_config_exists(self) -> None:
        assert DEPENDABOT.is_file()

    def test_ci_yaml_parses(self, ci: Dict[str, Any]) -> None:
        assert isinstance(ci, dict)
        assert ci.get("name", "").lower() == "ci"

    def test_release_yaml_parses(self, release: Dict[str, Any]) -> None:
        assert isinstance(release, dict)
        assert release.get("name", "").lower() == "release"

    def test_benchmark_yaml_parses(self, benchmark: Dict[str, Any]) -> None:
        assert isinstance(benchmark, dict)
        assert benchmark.get("name", "").lower() == "benchmark"

    def test_dependabot_yaml_parses(self, dependabot: Dict[str, Any]) -> None:
        assert dependabot.get("version") == 2
        assert isinstance(dependabot.get("updates"), list)


# ─── CI workflow ────────────────────────────────────────────────────

class TestCI:
    def _jobs(self, ci: Dict[str, Any]) -> Dict[str, Any]:
        return ci.get("jobs", {})

    def test_has_lint_job(self, ci: Dict[str, Any]) -> None:
        assert "lint" in self._jobs(ci)

    def test_has_unit_tests_job(self, ci: Dict[str, Any]) -> None:
        assert "unit-tests" in self._jobs(ci)

    def test_has_frontend_tests_job(self, ci: Dict[str, Any]) -> None:
        assert "frontend-tests" in self._jobs(ci)

    def test_has_integration_job(self, ci: Dict[str, Any]) -> None:
        assert "integration" in self._jobs(ci)

    def test_has_security_job(self, ci: Dict[str, Any]) -> None:
        assert "security" in self._jobs(ci)

    def test_has_docker_build_job(self, ci: Dict[str, Any]) -> None:
        assert "docker-build" in self._jobs(ci)

    def test_has_coverage_reporting_job(self, ci: Dict[str, Any]) -> None:
        assert "coverage" in self._jobs(ci)

    def test_lint_runs_ruff(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["lint"])
        assert "ruff" in text

    def test_lint_runs_mypy(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["lint"])
        assert "mypy" in text

    def test_unit_tests_run_pytest(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["unit-tests"])
        assert "pytest" in text
        assert "pytest-cov" in text or "cov" in text

    def test_integration_probes_health(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["integration"])
        assert "/health" in text or "health/live" in text or "health/ready" in text

    def test_security_uses_bandit(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["security"])
        assert "bandit" in text

    def test_security_uses_trivy(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["security"])
        assert "trivy" in text

    def test_docker_build_uses_buildx(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["docker-build"])
        assert "buildx" in text
        assert "build-push-action" in text

    def test_docker_builds_both_images(self, ci: Dict[str, Any]) -> None:
        text = _dump(ci["jobs"]["docker-build"])
        assert "Dockerfile.production" in text
        assert "regintel/backend" in text
        assert "regintel/frontend" in text

    def test_concurrency_set(self, ci: Dict[str, Any]) -> None:
        assert "concurrency" in ci

    def test_fail_fast_set(self, ci: Dict[str, Any]) -> None:
        assert ci.get("concurrency", {}).get("cancel-in-progress") is True

    def test_permissions_restricted(self, ci: Dict[str, Any]) -> None:
        perms = ci.get("permissions", {})
        assert perms.get("contents") == "read"

    def test_triggers_on_push_and_pr(self, ci: Dict[str, Any]) -> None:
        triggers = _triggers(ci)
        assert "push" in triggers
        assert "pull_request" in triggers


# ─── Release workflow ──────────────────────────────────────────────

class TestRelease:
    def _jobs(self, release: Dict[str, Any]) -> Dict[str, Any]:
        return release.get("jobs", {})

    def test_has_release_job(self, release: Dict[str, Any]) -> None:
        assert "release" in self._jobs(release)

    def test_release_uses_matrix(self, release: Dict[str, Any]) -> None:
        text = _dump(release["jobs"]["release"])
        assert "matrix" in text
        assert "backend" in text and "frontend" in text

    def test_release_uses_multi_arch(self, release: Dict[str, Any]) -> None:
        text = _dump(release["jobs"]["release"])
        assert "linux/amd64" in text
        assert "linux/arm64" in text

    def test_release_pushes_to_ghcr(self, release: Dict[str, Any]) -> None:
        # ghcr.io is referenced at the workflow-level ``env`` block, not inside
        # any single step — dump the entire workflow to check.
        text = _dump(release)
        assert "ghcr.io" in text
        # Permissions may be in either order: ``contents: read, packages: write``.
        perms = release.get("permissions", {})
        assert perms.get("packages") == "write"

    def test_release_runs_trivy(self, release: Dict[str, Any]) -> None:
        text = _dump(release["jobs"]["release"])
        assert "trivy" in text

    def test_release_triggers_on_tag(self, release: Dict[str, Any]) -> None:
        triggers = _triggers(release)
        assert "push" in triggers
        assert "tags" in triggers["push"]

    def test_release_supports_manual(self, release: Dict[str, Any]) -> None:
        triggers = _triggers(release)
        assert "workflow_dispatch" in triggers

    def test_release_uses_provenance_and_sbom(self, release: Dict[str, Any]) -> None:
        text = _dump(release["jobs"]["release"])
        assert "provenance" in text
        assert "sbom" in text


# ─── Benchmark workflow ───────────────────────────────────────────

class TestBenchmark:
    def _jobs(self, benchmark: Dict[str, Any]) -> Dict[str, Any]:
        return benchmark.get("jobs", {})

    def test_has_benchmark_job(self, benchmark: Dict[str, Any]) -> None:
        assert "benchmark" in self._jobs(benchmark)

    def test_runs_cli(self, benchmark: Dict[str, Any]) -> None:
        text = _dump(benchmark["jobs"]["benchmark"])
        assert "app.benchmark.cli" in text

    def test_uploads_artifacts(self, benchmark: Dict[str, Any]) -> None:
        text = _dump(benchmark["jobs"]["benchmark"])
        assert "upload-artifact" in text

    def test_supports_manual_suite_choice(self, benchmark: Dict[str, Any]) -> None:
        triggers = _triggers(benchmark)
        assert "workflow_dispatch" in triggers

    def test_scheduled(self, benchmark: Dict[str, Any]) -> None:
        triggers = _triggers(benchmark)
        sched = triggers.get("schedule", [])
        assert sched and "cron" in sched[0]

    def test_generates_reports(self, benchmark: Dict[str, Any]) -> None:
        text = _dump(benchmark["jobs"]["benchmark"])
        assert "report" in text


# ─── Dependabot ───────────────────────────────────────────────────

class TestDependabot:
    def test_has_pip_ecosystem(self, dependabot: Dict[str, Any]) -> None:
        assert any(
            u.get("package-ecosystem") == "pip" for u in dependabot["updates"]
        )

    def test_has_npm_ecosystem(self, dependabot: Dict[str, Any]) -> None:
        assert any(
            u.get("package-ecosystem") == "npm" for u in dependabot["updates"]
        )

    def test_has_github_actions_ecosystem(self, dependabot: Dict[str, Any]) -> None:
        assert any(
            u.get("package-ecosystem") == "github-actions"
            for u in dependabot["updates"]
        )
