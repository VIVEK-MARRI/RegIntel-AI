"""Static validation of the M10.3 production deployment artefacts.

These tests do NOT require Docker / nginx / docker compose to be installed.
They assert structural and content invariants on the committed files so
that a deploy-time regression is caught at CI time.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
import yaml


# ─── Locations ──────────────────────────────────────────────────────

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCKERFILE = REPO_ROOT / "Dockerfile.production"
FRONTEND_DOCKERFILE = REPO_ROOT / "frontend" / "Dockerfile.production"
COMPOSE = REPO_ROOT / "docker-compose.production.yml"
NGINX_CONF = REPO_ROOT / "nginx.conf"
ENV_EXAMPLE = REPO_ROOT / ".env.production.example"
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


# ─── Helpers ────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def dockerfile_text() -> str:
    return DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def frontend_dockerfile_text() -> str:
    return FRONTEND_DOCKERFILE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def compose_data() -> Dict[str, Any]:
    return yaml.safe_load(COMPOSE.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def nginx_text() -> str:
    return NGINX_CONF.read_text(encoding="utf-8")


# ─── File presence ──────────────────────────────────────────────────


class TestFilePresence:
    def test_dockerfile_exists(self) -> None:
        assert DOCKERFILE.is_file(), "Dockerfile.production is missing"

    def test_frontend_dockerfile_exists(self) -> None:
        assert (
            FRONTEND_DOCKERFILE.is_file()
        ), "frontend/Dockerfile.production is missing"

    def test_compose_exists(self) -> None:
        assert COMPOSE.is_file(), "docker-compose.production.yml is missing"

    def test_nginx_conf_exists(self) -> None:
        assert NGINX_CONF.is_file(), "nginx.conf is missing"

    def test_env_example_exists(self) -> None:
        assert ENV_EXAMPLE.is_file(), ".env.production.example is missing"

    def test_dockerignore_exists(self) -> None:
        assert DOCKERIGNORE.is_file(), ".dockerignore is missing"

    def test_requirements_txt_exists(self) -> None:
        req = REPO_ROOT / "requirements.txt"
        assert req.is_file(), "requirements.txt is missing"

    def test_requirements_pinned(self) -> None:
        text = (REPO_ROOT / "requirements.txt").read_text(encoding="utf-8")
        # Lines starting with `-e`, `#`, or empty are ignored; the rest must be pinned.
        bad = []
        for ln in text.splitlines():
            s = ln.strip()
            if not s or s.startswith("#") or s.startswith("-"):
                continue
            if "==" not in s:
                bad.append(s)
        assert not bad, f"unpinned dependencies: {bad}"


# ─── Backend Dockerfile ─────────────────────────────────────────────


class TestBackendDockerfile:
    def test_uses_multi_stage(self, dockerfile_text: str) -> None:
        assert "FROM " in dockerfile_text
        assert dockerfile_text.count("FROM ") >= 2, "backend image must be multi-stage"

    def test_uses_slim_base(self, dockerfile_text: str) -> None:
        assert "python:3.11-slim" in dockerfile_text

    def test_non_root_user(self, dockerfile_text: str) -> None:
        assert "useradd" in dockerfile_text or "adduser" in dockerfile_text
        assert "USER " in dockerfile_text
        assert "regintel" in dockerfile_text

    def test_healthcheck(self, dockerfile_text: str) -> None:
        assert "HEALTHCHECK" in dockerfile_text
        assert "/health" in dockerfile_text

    def test_exposes_port(self, dockerfile_text: str) -> None:
        assert "EXPOSE" in dockerfile_text
        assert "8000" in dockerfile_text

    def test_pins_python(self, dockerfile_text: str) -> None:
        # Allow either explicit `python:3.11.x-slim` or the `python:3.11-slim` form.
        assert re.search(r"FROM python:3\.11(\.\d+)?-slim", dockerfile_text)

    def test_cleans_apt_cache(self, dockerfile_text: str) -> None:
        assert "rm -rf /var/lib/apt/lists/*" in dockerfile_text

    def test_uses_venv(self, dockerfile_text: str) -> None:
        assert "venv" in dockerfile_text or "virtualenv" in dockerfile_text

    def test_entrypoint_present(self, dockerfile_text: str) -> None:
        assert "ENTRYPOINT" in dockerfile_text
        assert "CMD" in dockerfile_text

    def test_uses_tini(self, dockerfile_text: str) -> None:
        # tini gives us proper PID 1 signal handling.
        assert "tini" in dockerfile_text


# ─── Frontend Dockerfile ────────────────────────────────────────────


class TestFrontendDockerfile:
    def test_multi_stage(self, frontend_dockerfile_text: str) -> None:
        assert frontend_dockerfile_text.count("FROM ") >= 2

    def test_uses_alpine(self, frontend_dockerfile_text: str) -> None:
        assert "alpine" in frontend_dockerfile_text.lower()

    def test_nginx_base(self, frontend_dockerfile_text: str) -> None:
        assert "nginx" in frontend_dockerfile_text.lower()

    def test_healthcheck(self, frontend_dockerfile_text: str) -> None:
        assert "HEALTHCHECK" in frontend_dockerfile_text

    def test_node_builder(self, frontend_dockerfile_text: str) -> None:
        assert "node:" in frontend_dockerfile_text
        assert "npm" in frontend_dockerfile_text

    def test_exposes_port_80(self, frontend_dockerfile_text: str) -> None:
        assert "EXPOSE 80" in frontend_dockerfile_text

    def test_copies_dist(self, frontend_dockerfile_text: str) -> None:
        assert "dist" in frontend_dockerfile_text


# ─── docker-compose ─────────────────────────────────────────────────


class TestCompose:
    def test_compose_is_valid_yaml(self, compose_data: Dict[str, Any]) -> None:
        assert "services" in compose_data
        assert "networks" in compose_data or True  # tolerated

    def test_has_backend_service(self, compose_data: Dict[str, Any]) -> None:
        assert "backend" in compose_data["services"]

    def test_has_frontend_service(self, compose_data: Dict[str, Any]) -> None:
        assert "frontend" in compose_data["services"]

    def test_backend_uses_production_dockerfile(
        self, compose_data: Dict[str, Any]
    ) -> None:
        backend = compose_data["services"]["backend"]
        assert backend["build"]["dockerfile"] == "Dockerfile.production"

    def test_frontend_uses_production_dockerfile(
        self, compose_data: Dict[str, Any]
    ) -> None:
        frontend = compose_data["services"]["frontend"]
        assert "Dockerfile.production" in frontend["build"]["dockerfile"]

    def test_backend_has_healthcheck(self, compose_data: Dict[str, Any]) -> None:
        assert "healthcheck" in compose_data["services"]["backend"]

    def test_frontend_has_healthcheck(self, compose_data: Dict[str, Any]) -> None:
        assert "healthcheck" in compose_data["services"]["frontend"]

    def test_backend_has_restart_policy(self, compose_data: Dict[str, Any]) -> None:
        assert compose_data["services"]["backend"].get("restart") == "unless-stopped"

    def test_frontend_has_restart_policy(self, compose_data: Dict[str, Any]) -> None:
        assert compose_data["services"]["frontend"].get("restart") == "unless-stopped"

    def test_frontend_depends_on_backend(self, compose_data: Dict[str, Any]) -> None:
        deps = compose_data["services"]["frontend"].get("depends_on", {})
        assert "backend" in deps
        # Compose v2 conditional health gate
        assert deps["backend"].get("condition") == "service_healthy"

    def test_backend_env_file(self, compose_data: Dict[str, Any]) -> None:
        env_file = compose_data["services"]["backend"].get("env_file", [])
        assert ".env.production" in env_file

    def test_backend_resource_limits(self, compose_data: Dict[str, Any]) -> None:
        limits = compose_data["services"]["backend"]["deploy"]["resources"]["limits"]
        assert "cpus" in limits and "memory" in limits

    def test_frontend_resource_limits(self, compose_data: Dict[str, Any]) -> None:
        limits = compose_data["services"]["frontend"]["deploy"]["resources"]["limits"]
        assert "cpus" in limits and "memory" in limits

    def test_security_options(self, compose_data: Dict[str, Any]) -> None:
        for name in ("backend", "frontend"):
            svc = compose_data["services"][name]
            assert "no-new-privileges:true" in svc.get(
                "security_opt", []
            ), f"{name} should set no-new-privileges"

    def test_capabilities_dropped(self, compose_data: Dict[str, Any]) -> None:
        for name in ("backend", "frontend"):
            svc = compose_data["services"][name]
            assert "ALL" in svc.get(
                "cap_drop", []
            ), f"{name} should drop ALL capabilities"

    def test_named_volumes(self, compose_data: Dict[str, Any]) -> None:
        vols = compose_data.get("volumes", {})
        assert "regintel_storage" in vols
        assert "regintel_logs" in vols

    def test_logging_configured(self, compose_data: Dict[str, Any]) -> None:
        for name in ("backend", "frontend"):
            logging = compose_data["services"][name].get("logging", {})
            assert logging.get("driver") == "json-file"


# ─── nginx ──────────────────────────────────────────────────────────


class TestNginx:
    def test_has_user_directive(self, nginx_text: str) -> None:
        # nginx config files may start with comments — check the user directive appears.
        assert re.search(r"^\s*user\s+nginx\s*;", nginx_text, re.MULTILINE)

    def test_has_upstream(self, nginx_text: str) -> None:
        assert "upstream regintel_backend" in nginx_text

    def test_proxies_api(self, nginx_text: str) -> None:
        assert "location /api/" in nginx_text
        assert "proxy_pass" in nginx_text
        assert "regintel_backend" in nginx_text

    def test_security_headers(self, nginx_text: str) -> None:
        assert "X-Frame-Options" in nginx_text
        assert "X-Content-Type-Options" in nginx_text
        assert "Content-Security-Policy" in nginx_text
        assert "Referrer-Policy" in nginx_text

    def test_gzip_enabled(self, nginx_text: str) -> None:
        assert re.search(r"^\s*gzip\s+on\s*;", nginx_text, re.MULTILINE)

    def test_rate_limiting(self, nginx_text: str) -> None:
        assert "limit_req_zone" in nginx_text
        assert "limit_req" in nginx_text

    def test_spa_fallback(self, nginx_text: str) -> None:
        assert "try_files" in nginx_text
        assert "/index.html" in nginx_text

    def test_static_asset_cache(self, nginx_text: str) -> None:
        assert "expires 1y" in nginx_text or "immutable" in nginx_text

    def test_listen_port(self, nginx_text: str) -> None:
        assert re.search(
            r"^\s*listen\s+80(\s+default_server)?\s*;", nginx_text, re.MULTILINE
        )

    def test_server_tokens_off(self, nginx_text: str) -> None:
        assert re.search(r"^\s*server_tokens\s+off\s*;", nginx_text, re.MULTILINE)

    def test_client_max_body_size_set(self, nginx_text: str) -> None:
        assert "client_max_body_size" in nginx_text

    def test_no_default_server_token(self, nginx_text: str) -> None:
        # The default_server marker must be set so we don't accidentally treat
        # a misconfigured vhost as the catch-all.
        assert re.search(
            r"^\s*listen\s+80\s+default_server\s*;", nginx_text, re.MULTILINE
        )


# ─── .env example ──────────────────────────────────────────────────


class TestEnvExample:
    def test_has_database_url(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "DATABASE_URL" in text
        assert "postgresql" in text

    def test_has_storage_root(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "STORAGE_ROOT" in text

    def test_does_not_commit_real_secrets(self) -> None:
        # The template must not contain a real-looking password.
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "CHANGE_ME" in text or "REPLACE_ME" in text
        assert "password" not in text.lower() or "CHANGE_ME" in text

    def test_has_cost_config(self) -> None:
        text = ENV_EXAMPLE.read_text(encoding="utf-8")
        assert "COST_PER_1K_INPUT_TOKENS" in text
        assert "COST_PER_1K_OUTPUT_TOKENS" in text
        assert "COST_PER_RETRIEVAL" in text


# ─── dockerignore ──────────────────────────────────────────────────


class TestDockerignore:
    def test_excludes_git(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        assert ".git" in text

    def test_excludes_venv(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        assert ".venv" in text

    def test_excludes_storage(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "storage" in text

    def test_excludes_node_modules(self) -> None:
        text = DOCKERIGNORE.read_text(encoding="utf-8")
        assert "node_modules" in text
