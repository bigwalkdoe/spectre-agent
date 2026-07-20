# Spectre Agent

Spectre is an autonomous AI Engineering Operating System for Fedora Linux. It monitors, maintains, secures, and manages a Linux workstation through agents, workflows, plugins, and a CLI/API/daemon.

## Operating Principles

1. **Kernel-first** — All components boot through the Kernel with DI and lifecycle management.
2. **ServiceBus communication** — Agents communicate only through the ServiceBus; no direct coupling.
3. **Event-driven** — Workflow steps publish events for plugin hooks and inter-agent coordination.
4. **Fail fast** — A failed step stops the workflow unless `continue_on_failure` is set.
5. **Stateful** — All actions persisted in SQLite (`~/.config/spectre/memory.db`).

## Structure

```
spectre/
├── AGENTS.md                    # This file
├── README.md                    # Overview and usage
├── pyproject.toml
├── packages/
│   ├── core/                    # Kernel, DI, ServiceBus, EventBus
│   │   ├── kernel.py            # Bootstrap, lifecycle, DI container
│   │   ├── service_bus.py       # Inter-agent communication
│   │   ├── event_bus.py         # Pub/sub event system
│   │   ├── config.py            # 4-level config hierarchy
│   │   ├── scheduler.py         # Task scheduler (cron/interval)
│   │   └── agent.py             # BaseAgent ABC + AgentContext
│   ├── config/                  # Configuration management
│   │   └── settings.py          # YAML settings with Pydantic
│   ├── memory/                  # Persistent storage
│   │   └── db.py                # SQLite via SQLModel (12 tables)
│   ├── plugins/                 # Plugin system
│   │   └── loader.py            # Manifest, permissions, hooks, ServiceBus
│   ├── workflow_engine/         # Workflow orchestration
│   │   └── engine.py            # Data-driven workflows with events
│   ├── linux_agent/             # Linux maintenance
│   ├── devops_agent/            # Container management
│   ├── security_agent/          # Security auditing
│   ├── ai_agent/                # AI model management
│   ├── developer_agent/         # Development tools
│   ├── monitoring_agent/        # System metrics
│   ├── documentation_agent/     # Documentation
│   └── publishing_agent/        # Release management
├── apps/
│   ├── cli/main.py              # 19 CLI commands
│   ├── api/main.py              # FastAPI REST API + dashboard
│   └── daemon/main.py           # Kernel-based background daemon
├── config/                      # Configuration files
├── tests/                       # Test suite (145 tests)
├── docs/                        # Documentation
└── scripts/                     # Installation and utilities
```

## Standards

- Python 3.11+, ruff (lint), mypy (types), pytest (tests)
- Structured state via dataclasses; SQLite persistence
- Agents register with ServiceBus during `initialize()`
- Events published before/after workflow steps
