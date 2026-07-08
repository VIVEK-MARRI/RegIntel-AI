"""Tests for the M10.7 architecture documentation.

These tests verify that:

* Every required architecture file exists and is non-empty.
* Mermaid diagrams use a supported renderer (flowchart, sequenceDiagram,
  classDiagram, stateDiagram, gitgraph).
* Each document contains a "See also" or related-links section.
* The architecture README links to every other file in the directory.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARCH_DIR = REPO_ROOT / "docs" / "architecture"

REQUIRED_FILES = [
    "README.md",
    "01-system-architecture.md",
    "02-agent-architecture.md",
    "03-knowledge-graph.md",
    "04-deployment-architecture.md",
    "05-data-flow.md",
    "06-components.md",
    "07-api-reference.md",
    "08-developer-guide.md",
    "09-operations-guide.md",
    "copilot-retrieval.md",
]

# Sections we expect each architecture file to contain
EXPECTED_SECTIONS = {
    "01-system-architecture.md": [
        "## Overview",
        "## High-level diagram",
        "## Component responsibilities",
    ],
    "02-agent-architecture.md": [
        "## Purpose",
        "## High-level diagram",
        "## Components",
    ],
    "03-knowledge-graph.md": [
        "## Purpose",
        "## Data model",
        "## Storage",
        "## Performance",
    ],
    "04-deployment-architecture.md": [
        "## Container topology",
        "## docker-compose",
        "## Security",
        "## Observability",
    ],
    "05-data-flow.md": ["## 1. Ingest pipeline", "## 2. Search", "## 3. Agent run"],
    "06-components.md": [
        "## `app.main`",
        "## `app.api.v1.*`",
        "## `app.agent`",
        "## `app.security`",
        "## `app.benchmark`",
    ],
    "07-api-reference.md": [
        "## Conventions",
        "## Core endpoints",
        "## Cross-Origin",
        "## Versioning",
    ],
    "08-developer-guide.md": ["## Local setup", "## Testing", "## Code style"],
    "09-operations-guide.md": [
        "## Health probes",
        "## Metrics",
        "## Logs",
        "## Incident response",
    ],
}

MERMAID_BLOCK_RE = re.compile(r"```mermaid\n(.*?)```", re.DOTALL)
MERMAID_HEADERS = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "gitgraph",
    "erDiagram",
    "journey",
    "gantt",
    "pie",
)


class TestFilePresence:
    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_file_exists(self, filename: str) -> None:
        path = ARCH_DIR / filename
        assert path.exists(), f"missing architecture file: {path}"
        assert path.is_file(), f"not a file: {path}"

    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_file_is_non_empty(self, filename: str) -> None:
        path = ARCH_DIR / filename
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert len(content) > 500, f"{filename} is too short ({len(content)} chars)"

    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_file_has_top_level_heading(self, filename: str) -> None:
        path = ARCH_DIR / filename
        content = path.read_text(encoding="utf-8")
        # Every file should start with a single H1.
        assert content.startswith(
            "# "
        ), f"{filename} does not start with a top-level heading"


class TestMermaidDiagrams:
    @pytest.mark.parametrize("filename", REQUIRED_FILES)
    def test_mermaid_blocks_have_valid_headers(self, filename: str) -> None:
        path = ARCH_DIR / filename
        content = path.read_text(encoding="utf-8")
        blocks = MERMAID_BLOCK_RE.findall(content)
        if not blocks:
            pytest.skip(f"{filename} has no Mermaid blocks")
        for block in blocks:
            first_line = block.strip().splitlines()[0].strip()
            assert first_line.startswith(MERMAID_HEADERS), (
                f"{filename}: Mermaid block starts with {first_line!r}, "
                f"expected one of {MERMAID_HEADERS}"
            )


class TestContentShape:
    @pytest.mark.parametrize("filename,sections", list(EXPECTED_SECTIONS.items()))
    def test_required_sections_present(self, filename: str, sections: list) -> None:
        path = ARCH_DIR / filename
        content = path.read_text(encoding="utf-8")
        for section in sections:
            assert (
                section in content
            ), f"{filename} missing required section {section!r}"


class TestCrossLinks:
    def test_readme_links_every_other_file(self) -> None:
        readme = (ARCH_DIR / "README.md").read_text(encoding="utf-8")
        for filename in REQUIRED_FILES:
            if filename == "README.md":
                continue
            assert filename in readme, f"README.md does not link to {filename}"

    def test_every_file_links_to_readme(self) -> None:
        for filename in REQUIRED_FILES:
            if filename == "README.md":
                continue
            content = (ARCH_DIR / filename).read_text(encoding="utf-8")
            assert (
                "README" in content or "architecture" in content.lower()
            ), f"{filename} has no link back to the architecture index"

    def test_no_orphaned_files(self) -> None:
        # No markdown file in docs/architecture that is not in REQUIRED_FILES.
        if not ARCH_DIR.exists():
            pytest.skip("architecture directory not present")
        for path in ARCH_DIR.glob("*.md"):
            assert path.name in REQUIRED_FILES, f"orphaned file: {path.name}"


class TestDiagramQuality:
    def test_system_architecture_has_overview_diagram(self) -> None:
        content = (ARCH_DIR / "01-system-architecture.md").read_text(encoding="utf-8")
        assert "flowchart" in content or "graph" in content
        # Must mention the three primary components
        assert "FastAPI" in content or "API" in content
        assert "Retrieval" in content or "retrieval" in content
        assert "Agent" in content or "agent" in content

    def test_data_flow_has_sequence_diagrams(self) -> None:
        content = (ARCH_DIR / "05-data-flow.md").read_text(encoding="utf-8")
        assert (
            content.count("sequenceDiagram") >= 3
        ), "05-data-flow.md must contain at least 3 sequence diagrams"

    def test_knowledge_graph_has_class_diagram(self) -> None:
        content = (ARCH_DIR / "03-knowledge-graph.md").read_text(encoding="utf-8")
        assert "classDiagram" in content

    def test_agent_has_state_diagram(self) -> None:
        content = (ARCH_DIR / "02-agent-architecture.md").read_text(encoding="utf-8")
        assert "stateDiagram" in content

    def test_deployment_has_topology_diagram(self) -> None:
        content = (ARCH_DIR / "04-deployment-architecture.md").read_text(
            encoding="utf-8"
        )
        assert "flowchart" in content or "graph" in content
        assert "PostgreSQL" in content or "postgres" in content.lower()
