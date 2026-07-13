# Spectre Agent

Spectre Agent is a deployment orchestrator for containerized services. It deploys, monitors, and rollbacks services across environments.

## Operating Principles

1. **Sequential stages** — Every deployment runs through pre-check → build → deploy → health-check → record in order.
2. **Fail fast** — A failed stage stops the deployment immediately; no partial state.
3. **Stateful** — Deployment history is persisted in `.spectre/deployments.json`.
4. **Read-only default** — CLI reports status and history without side effects. Only `deploy` and `rollback` mutate state.

## Structure

```
spectre-agent/
├── AGENTS.md              # This file
├── README.md              # Overview and usage
├── pyproject.toml
├── src/spectre/
│   ├── cli.py             # CLI entrypoint (deploy, rollback, status, list)
│   ├── models.py          # Dataclasses (Deployment, Stage, StepResult)
│   ├── orchestrator.py    # Deployment pipeline orchestrator
│   ├── builder.py         # Build service artifacts (docker, pip)
│   ├── deployer.py        # Deploy to environments (compose, kubectl)
│   ├── checker.py         # Pre-deploy and health checks
│   ├── rollback.py        # Rollback to previous version
│   ├── state.py           # Deployment state persistence
│   └── report.py          # Reports and changelog recording
├── config/                # Service and environment definitions
├── playbooks/             # Deployment runbooks
├── scripts/               # Helper automation
└── memory/                # Changelog and decisions
```

## Standards

- Python 3.11+, ruff (lint), mypy (types), pytest (tests)
- Structured state via dataclasses; JSON persistence for deployment history
- No external dependencies in the core library
