"""Tests for the M10.8 release artifacts.

Verifies that:

* Every required release artifact exists and is non-empty.
* The release notes follow the expected structure.
* The deployment, operations, user, admin, and troubleshooting guides
  contain their mandatory sections.
* The versioning policy is consistent with the implementation.
* The release checklist is complete (all checkboxes present).
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
DOCS_DIR = REPO_ROOT / "docs"

REQUIRED_RELEASE_FILES = [
    "DEPLOYMENT.md",
    "OPERATIONS.md",
    "USER_GUIDE.md",
    "ADMIN_GUIDE.md",
    "TROUBLESHOOTING.md",
    "VERSIONING.md",
    "RELEASE_CHECKLIST.md",
]

REQUIRED_TOP_LEVEL = ["RELEASE_NOTES.md"]

SEMVER_RE = re.compile(
    r"^v?(\d+)\.(\d+)\.(\d+)(?:-([A-Za-z0-9.-]+))?(?:\+([A-Za-z0-9.-]+))?$"
)


# ─── File presence ────────────────────────────────────────────────


class TestFilePresence:
    @pytest.mark.parametrize("filename", REQUIRED_TOP_LEVEL)
    def test_top_level_exists(self, filename: str) -> None:
        path = REPO_ROOT / filename
        assert path.exists(), f"missing top-level release file: {path}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 500, f"{filename} is too short"

    @pytest.mark.parametrize("filename", REQUIRED_RELEASE_FILES)
    def test_doc_exists(self, filename: str) -> None:
        path = DOCS_DIR / filename
        assert path.exists(), f"missing release doc: {path}"
        content = path.read_text(encoding="utf-8")
        assert len(content) > 500, f"{filename} is too short"


# ─── Release notes structure ──────────────────────────────────────


class TestReleaseNotes:
    REQUIRED_SECTIONS = [
        "Highlights",
        "What's new",
        "Breaking changes",
        "Security",
        "Upgrading",
        "Assets",
    ]

    def test_required_sections(self) -> None:
        content = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            assert section in content, f"RELEASE_NOTES.md missing section {section!r}"

    def test_includes_semver_tag(self) -> None:
        content = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        # The release notes should declare the current version.
        match = re.search(r"v\d+\.\d+\.\d+(?:-[A-Za-z0-9.-]+)?", content)
        assert match, "RELEASE_NOTES.md does not declare a semantic version"
        assert SEMVER_RE.match(
            match.group()
        ), f"RELEASE_NOTES.md version {match.group()!r} is not valid semver"

    def test_lists_assets(self) -> None:
        content = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        # Must include at least the backend and frontend image references
        assert "backend" in content
        assert "frontend" in content
        # And a registry URL
        assert "ghcr.io" in content


# ─── Deployment guide ────────────────────────────────────────────


class TestDeploymentGuide:
    REQUIRED_SECTIONS = [
        "Prerequisites",
        "Prepare the secrets",
        "Apply the database schema",
        "Pull and start",
        "Smoke test",
        "Disable the dev token endpoint",
    ]

    def test_required_sections(self) -> None:
        content = (DOCS_DIR / "DEPLOYMENT.md").read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            assert section in content, f"DEPLOYMENT.md missing section {section!r}"

    def test_lists_jwt_secret_requirement(self) -> None:
        content = (DOCS_DIR / "DEPLOYMENT.md").read_text(encoding="utf-8")
        assert "REGINTEL_JWT_SECRET" in content
        assert "32" in content  # must call out the 32-char minimum

    def test_disable_dev_token_documented(self) -> None:
        content = (DOCS_DIR / "DEPLOYMENT.md").read_text(encoding="utf-8")
        assert "SECURITY_DEV_TOKEN_ENDPOINT" in content


# ─── Operations guide ────────────────────────────────────────────


class TestOperationsGuide:
    REQUIRED_SECTIONS = [
        "SLOs",
        "Monitoring",
        "On-call",
        "Capacity planning",
        "Disaster recovery",
    ]

    def test_required_sections(self) -> None:
        content = (DOCS_DIR / "OPERATIONS.md").read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            assert section in content, f"OPERATIONS.md missing section {section!r}"

    def test_defines_severity_levels(self) -> None:
        content = (DOCS_DIR / "OPERATIONS.md").read_text(encoding="utf-8")
        for sev in ("Sev-1", "Sev-2", "Sev-3", "Sev-4"):
            assert sev in content, f"OPERATIONS.md missing severity level {sev!r}"


# ─── User guide ──────────────────────────────────────────────────


class TestUserGuide:
    REQUIRED_SECTIONS = [
        "Quick start",
        "Roles",
        "Common tasks",
        "Tips",
    ]

    def test_required_sections(self) -> None:
        content = (DOCS_DIR / "USER_GUIDE.md").read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            assert section in content, f"USER_GUIDE.md missing section {section!r}"

    def test_role_matrix(self) -> None:
        content = (DOCS_DIR / "USER_GUIDE.md").read_text(encoding="utf-8")
        for role in ("Viewer", "Analyst", "Operator", "Auditor", "Admin", "Service"):
            assert role in content, f"USER_GUIDE.md missing role {role!r}"


# ─── Admin guide ─────────────────────────────────────────────────


class TestAdminGuide:
    REQUIRED_SECTIONS = [
        "Users",
        "API keys",
        "Quotas",
        "Knowledge graph",
        "Governance",
        "Security",
        "Compliance",
    ]

    def test_required_sections(self) -> None:
        content = (DOCS_DIR / "ADMIN_GUIDE.md").read_text(encoding="utf-8")
        for section in self.REQUIRED_SECTIONS:
            assert section in content, f"ADMIN_GUIDE.md missing section {section!r}"

    def test_rotation_procedure(self) -> None:
        content = (DOCS_DIR / "ADMIN_GUIDE.md").read_text(encoding="utf-8")
        assert "Rotate" in content or "rotate" in content
        assert "JWT" in content


# ─── Troubleshooting guide ───────────────────────────────────────


class TestTroubleshootingGuide:
    REQUIRED_SECTIONS = [
        "5xx",
        "401",
        "403",
        "429",
    ]

    def test_required_status_codes_documented(self) -> None:
        content = (DOCS_DIR / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        for code in self.REQUIRED_SECTIONS:
            assert code in content, f"TROUBLESHOOTING.md missing error code {code!r}"

    def test_diagnose_section_present(self) -> None:
        content = (DOCS_DIR / "TROUBLESHOOTING.md").read_text(encoding="utf-8")
        assert "Diagnose" in content
        assert "Common causes" in content


# ─── Versioning policy ───────────────────────────────────────────


class TestVersioning:
    def test_semver_format_documented(self) -> None:
        content = (DOCS_DIR / "VERSIONING.md").read_text(encoding="utf-8")
        assert "Semantic Versioning" in content
        assert "MAJOR" in content
        assert "MINOR" in content
        assert "PATCH" in content

    def test_deprecation_policy_documented(self) -> None:
        content = (DOCS_DIR / "VERSIONING.md").read_text(encoding="utf-8")
        assert "deprecat" in content.lower()
        assert "Sunset" in content or "sunset" in content

    def test_release_channels_documented(self) -> None:
        content = (DOCS_DIR / "VERSIONING.md").read_text(encoding="utf-8")
        for channel in ("Stable", "RC", "Beta", "Nightly"):
            assert channel in content, f"VERSIONING.md missing channel {channel!r}"

    def test_app_version_matches_release(self) -> None:
        # Cross-check the declared version in code with the version in the
        # release notes — they must agree.
        import app

        try:
            code_version = app.__version__
        except AttributeError:
            pytest.skip("app.__version__ not defined")
        release = (REPO_ROOT / "RELEASE_NOTES.md").read_text(encoding="utf-8")
        # Strip any pre-release suffix for the comparison.
        base_code = code_version.split("-")[0]
        assert (
            base_code in release
        ), f"app.__version__={code_version!r} not found in RELEASE_NOTES.md"


# ─── Release checklist ───────────────────────────────────────────


class TestReleaseChecklist:
    PHASES = [
        "Pre-release",
        "Version bump",
        "Migration",
        "Build",
        "Smoke test on staging",
        "Promote to production",
        "Post-release",
    ]

    def test_phases_present(self) -> None:
        content = (DOCS_DIR / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        for phase in self.PHASES:
            assert phase in content, f"RELEASE_CHECKLIST.md missing phase {phase!r}"

    def test_uses_checkbox_format(self) -> None:
        content = (DOCS_DIR / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        # Should have at least 30 checkboxes
        checkboxes = re.findall(r"^- \[[ x]\]", content, re.MULTILINE)
        assert (
            len(checkboxes) >= 30
        ), f"RELEASE_CHECKLIST.md has only {len(checkboxes)} checkboxes, expected >= 30"

    def test_smoke_test_mentions_security_selftest(self) -> None:
        content = (DOCS_DIR / "RELEASE_CHECKLIST.md").read_text(encoding="utf-8")
        assert "security/selftest" in content
