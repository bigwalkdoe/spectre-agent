# Spectre Agent

Spectre is an autonomous AI Engineering Operating System for Fedora Linux. It monitors, maintains, secures, and manages a Linux workstation through intelligent agents, automated workflows, plugins, and a CLI/API/daemon architecture.

## Operating Principles

1. **Kernel-first** — All components boot through the Kernel with DI and lifecycle management.
2. **ServiceBus communication** — Agents communicate only through the ServiceBus; no direct coupling.
3. **Event-driven** — Workflow steps publish events for plugin hooks and inter-agent coordination.
4. **Fail fast** — A failed step stops the workflow unless `continue_on_failure` is set.
5. **Stateful** — All actions persisted in SQLite (`~/.config/spectre/memory.db`).
6. **Real integration** — All agents use real system calls (psutil, subprocess, httpx).
7. **Secure by default** — API key authentication, minimal privileges, no secrets in code.

## Structure

```
spectre/
├── AGENTS.md                    # This file
├── README.md                    # Overview and usage
├── LICENSE                      # MIT License
├── pyproject.toml               # Build config, entry point: apps.cli.main:main
├── Dockerfile                   # Container build
├── docker-compose.yml           # Easy deployment
├── packages/
│   ├── core/                    # Kernel, DI, ServiceBus, EventBus
│   │   ├── kernel.py            # Bootstrap, lifecycle, DI container
│   │   ├── service_bus.py       # Inter-agent communication, persistent registry
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
│   │   └── engine.py            # Data-driven workflows with ServiceBus resolution
│   ├── linux_agent/             # Linux maintenance (psutil, subprocess)
│   ├── devops_agent/            # Container management (podman, docker, kubectl)
│   ├── security_agent/          # Security auditing (SELinux, firewall, ports)
│   ├── ai_agent/                # AI model management (Ollama API)
│   ├── developer_agent/         # Development tools (git, pytest, ruff, mypy)
│   ├── monitoring_agent/        # System metrics (psutil)
│   ├── documentation_agent/     # Documentation (file system ops)
│   └── publishing_agent/        # Release management (git, pyproject)
├── apps/
│   ├── cli/main.py              # 31 CLI commands
│   ├── api/main.py              # FastAPI REST API (24 endpoints, API key auth)
│   └── daemon/main.py           # Kernel-based background daemon
├── config/                      # Configuration files
├── tests/                       # Test suite (189 tests)
├── docs/                        # Documentation
└── scripts/                     # Installation and utilities
```

## CLI Commands (31 total)

### System Commands
- `spectre init` — Initialize Spectre configuration
- `spectre doctor` — System diagnostics (`--fix` to auto-repair)
- `spectre health` — System health metrics
- `spectre status` — Overall system status (`--json`, `--watch N`)
- `spectre monitor` — Live system metrics
- `spectre dashboard` — Interactive TUI dashboard
- `spectre version` — Version and system info

### Maintenance Commands
- `spectre update` — Check for system updates
- `spectre clean` — Clean caches and packages
- `spectre repair` — System repair
- `spectre optimize` — Optimization workflows
- `spectre backup` — Backup configuration
- `spectre restore` — Restore configuration

### Security Commands
- `spectre security` — Security auditing (`--audit`, `--fix`)

### Container Commands
- `spectre services` — Systemd services
- `spectre containers` — Container management
- `spectre models` — AI models (Ollama)

### Workflow Commands
- `spectre workflows` — Execute/list/load workflows (`--load`, `--definitions`)
- `spectre schedule` — Manage scheduled tasks (`add`, `remove`, `run`, `list`)

### Management Commands
- `spectre kernel` — Kernel lifecycle (`status`, `start`, `stop`)
- `spectre service-bus` — Inspect ServiceBus (`--list`, `--topics`)
- `spectre core` — Core status
- `spectre plugins` — Manage plugins (`--install`, `--load`, `--list`, `--search`, `--remove`)
- `spectre config` — Manage configuration (`--show`, `--get`, `--set`)
- `spectre events` — View system events (`--type`, `--limit`)
- `spectre daemon` — Manage daemon (`start`, `stop`, `status`)
- `spectre logs` — View daemon logs (`-n`, `-f`)

### Data Commands
- `spectre export` — Export data (`--format json/csv`)
- `spectre import` — Import data from JSON
- `spectre report` — Generate reports

## API Endpoints (24 total)

All endpoints support API key authentication via `X-API-Key` header.

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/version` | GET | Version info |
| `/api/agents` | GET | List agents |
| `/api/agents/{name}` | GET | Agent status |
| `/api/workflows` | GET | List workflows |
| `/api/workflows/{name}` | POST | Run workflow |
| `/api/workflows/history` | GET | Workflow history |
| `/api/workflows/definitions` | GET | Workflow definitions |
| `/api/workflows/load` | POST | Load custom workflows |
| `/api/system/status` | GET | System status |
| `/api/core/kernel` | GET | Kernel status |
| `/api/core/kernel/start` | POST | Start Kernel |
| `/api/core/kernel/stop` | POST | Stop Kernel |
| `/api/core/service-bus` | GET | ServiceBus status |
| `/api/events` | GET | System events |
| `/api/schedule` | GET/POST | Schedule management |
| `/api/schedule/{name}` | DELETE | Remove schedule |
| `/api/reports` | GET | List reports |
| `/api/reports/{id}` | GET | Get report |
| `/api/config/{key}` | GET/PUT | Config management |
| `/api/decisions` | GET | List decisions |

## Agents (8 total)

| Agent | System Calls | Actions |
|-------|--------------|---------|
| **linux** | psutil, subprocess | system-health-check, dnf-check-update, flatpak-prune, journal-cleanup, selinux-check, firewall-check |
| **monitoring** | psutil | collect-metrics, check-thresholds |
| **security** | psutil, subprocess | selinux-audit, firewall-audit, ports-audit, secrets-scan, ssh-audit |
| **devops** | subprocess | podman-status, podman-prune, docker-status, docker-prune, kubectl-status |
| **ai** | httpx (Ollama API) | ollama-ping, list-models, benchmark-model |
| **developer** | subprocess | git-status, dependency-audit, test-runner, lint-check, type-check |
| **documentation** | file ops | scan-docs, check-links, coverage-report |
| **publishing** | subprocess, file ops | check-version, validate-dist, check-git-status |

## Workflows

### Built-in Workflows (10)
- `morning-startup` — Daily startup routine
- `weekly-maintenance` — Complete weekly maintenance
- `security-audit` — Full security audit
- `container-cleanup` — Prune containers
- `model-cleanup` — AI model maintenance
- `shutdown` — Pre-shutdown checks
- `monthly-optimization` — Monthly optimization
- `dependency-updates` — Check for updates
- `backup` — Backup verification
- `restore` — Post-restore verification

### Custom Workflows
Load custom workflows from YAML or JSON:

```yaml
name: my-workflow
description: Custom workflow
steps:
  - agent: linux
    action: system-health-check
  - agent: security
    action: ports-audit
    max_retries: 2
on_complete: "custom.done"
```

## Database

SQLite at `~/.config/spectre/memory.db` with 12 tables:

| Table | Purpose |
|-------|---------|
| `SystemMetric` | CPU, RAM, disk, battery, temperature history |
| `MaintenanceRecord` | Agent action results |
| `SecurityIncident` | Security findings |
| `Configuration` | Key-value config storage |
| `Report` | Generated reports |
| `WorkflowRun` | Workflow execution history |
| `Decision` | Decision audit log |
| `KVStore` | General key-value store |
| `Machine` | Machine identity and metadata |
| `AgentRecord` | Agent execution audit trail |
| `PluginRecord` | Plugin lifecycle tracking |
| `EventLog` | System event log |

## Testing

```bash
# Run all tests
pytest

# Run with coverage
pytest --cov=packages --cov=apps

# Run specific test file
pytest tests/test_agents.py -v
```

## Development

```bash
# Install development dependencies
pip install -e ".[dev]"

# Run linter
ruff check .

# Run type checker
mypy .

# Run formatter
ruff format .
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## License

MIT License - see [LICENSE](LICENSE) for details.
