# RegIntel AI — Architecture (M10.7)

> Comprehensive architecture documentation for the RegIntel AI platform.
> All diagrams are Mermaid and render natively on GitHub / GitLab.

## Index

| # | Document | Purpose |
|---|----------|---------|
| 01 | [System Architecture](./01-system-architecture.md) | High-level components, request flow, runtime topology |
| 02 | [Agent Architecture](./02-agent-architecture.md) | Retrieval-augmented agent, tools, planners, reasoning |
| 03 | [Knowledge Graph Architecture](./03-knowledge-graph.md) | Entity/relation store, vector + graph hybrid retrieval |
| 04 | [Deployment Architecture](./04-deployment-architecture.md) | Container, network, secrets, observability topology |
| 05 | [Data Flow](./05-data-flow.md) | Sequence + class diagrams for ingest, search, agent run |
| 06 | [Component Reference](./06-components.md) | Per-package responsibilities and dependencies |
| 07 | [API Reference](./07-api-reference.md) | REST surface, auth, error model, rate limits |
| 08 | [Developer Guide](./08-developer-guide.md) | Local dev, testing, contributing, code style |
| 09 | [Operations Guide](./09-operations-guide.md) | Runbooks, metrics, log/metric/trace conventions |
| 10 | [Copilot Retrieval ADR](./copilot-retrieval.md) | Copilot retrieval wiring decision and rationale |

## Audience

* **Engineers** onboarding to the codebase → start with [01](./01-system-architecture.md), [02](./02-agent-architecture.md), [08](./08-developer-guide.md).
* **Operators** running the platform → start with [04](./04-deployment-architecture.md), [09](./09-operations-guide.md).
* **Integrators** calling the API → start with [07](./07-api-reference.md).
* **Architects** reviewing design trade-offs → read all of the above.

## Conventions

* All Mermaid diagrams use the GitHub-flavored variant.
* Module paths are written as `app.module.submodule` and link to the
  corresponding source files via `path:line` references where useful.
* Diagram nodes are colour-coded:

  | Colour | Meaning |
  |--------|---------|
  | Blue (`#cfe2ff`) | Stateless service |
  | Green (`#d1e7dd`) | Stateful / persistent component |
  | Yellow (`#fff3cd`) | External dependency |
  | Red (`#f8d7da`)    | Security-sensitive component |
  | Grey (`#e2e3e5`)   | Optional / scaling-only component |

## Versioning

This documentation tracks the codebase at version `v1.0.0-rc1` (M10
release candidate). Diagrams are kept in lockstep with code; PRs that
change the architecture MUST update the corresponding diagram.
