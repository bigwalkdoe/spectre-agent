# Spectre

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-296%20passing-brightgreen.svg)](#testing)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-black.svg)](https://github.com/astral-sh/ruff)
[![Type Checked](https://img.shields.io/badge/type%20checked-mypy-blue.svg)](https://mypy-lang.org/)

**Autonomous AI Engineering Operating System for Fedora Linux**

Spectre monitors, maintains, secures, and manages your Linux workstation through intelligent agents, automated workflows, and a powerful CLI/API/daemon architecture.

## Features

- **8 Intelligent Agents** — Real system integration with psutil, subprocess, and API calls
- **30 CLI Commands** — Complete control from the terminal
- **24 REST API Endpoints** — Programmatic access with API key authentication
- **Enterprise TUI** — Interactive Textual dashboard with real-time metrics
- **Custom Workflows** — Load and execute YAML/JSON workflows at runtime
- **Scheduled Tasks** — Cron and interval-based automation
- **Plugin System** — Extensible architecture with manifest-based plugins
- **Data Import/Export** — JSON and CSV support
- **Docker Support** — Containerized deployment with docker-compose

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/bigwalkdoe/spectre-system-maintenance-agent.git
cd spectre

# Install in development mode
pip install -e ".[dev]"

# Initialize Spectre
spectre init
```

### First Run

```bash
# Check system health
spectre doctor

# View system status
spectre status

# Launch enterprise TUI dashboard
spectre dashboard

# Run a workflow
spectre workflows morning-startup

# Start the daemon
spectre daemon start
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / API                            │
│  (30 commands, 25 endpoints, TUI dashboard, JSON output)   │
├─────────────────────────────────────────────────────────────┤
│                     WorkflowEngine                          │
│    (ServiceBus resolution + EventBus event publishing)      │
│    (Custom YAML/JSON workflows, scheduled execution)        │
├─────────────────────────────────────────────────────────────┤
│                      ServiceBus                             │
│     (request/response, pub/sub, persistent registry)        │
├─────────────────────────────────────────────────────────────┤
│                       EventBus                              │
│          (workflow.* events, plugin hooks)                  │
├─────────────────────────────────────────────────────────────┤
│                       Kernel                                │
│    (DI container, lifecycle, scheduler, plugin loader)      │
├─────────────────────────────────────────────────────────────┤
│  linux  │  devops  │  security  │  ai  │  developer  │ ... │
│         plugins register as services on load               │
└─────────────────────────────────────────────────────────────┘
```

## CLI Reference

### System Commands
| Command | Description |
|---------|-------------|
| `spectre init` | Initialize Spectre configuration |
| `spectre doctor` | System diagnostics (`--fix` to auto-repair) |
| `spectre health` | System health metrics |
| `spectre status` | Overall system status (`--json`, `--watch N`) |
| `spectre monitor` | Live system metrics |
| `spectre dashboard` | Interactive TUI dashboard |
| `spectre version` | Version and system info |

### Maintenance Commands
| Command | Description |
|---------|-------------|
| `spectre update` | Check for system updates |
| `spectre clean` | Clean caches and packages |
| `spectre repair` | System repair |
| `spectre optimize` | Optimization workflows |
| `spectre backup` | Backup configuration |
| `spectre restore` | Restore configuration |

### Security Commands
| Command | Description |
|---------|-------------|
| `spectre security` | Security auditing (`--audit`, `--fix`) |

### Container Commands
| Command | Description |
|---------|-------------|
| `spectre services` | Systemd services |
| `spectre containers` | Container management |
| `spectre models` | AI models (Ollama) |

### Workflow Commands
| Command | Description |
|---------|-------------|
| `spectre workflows` | Execute/list/load workflows |
| `spectre schedule` | Manage scheduled tasks |

### Management Commands
| Command | Description |
|---------|-------------|
| `spectre kernel` | Kernel lifecycle |
| `spectre service-bus` | Inspect ServiceBus |
| `spectre core` | Core status |
| `spectre plugins` | Manage plugins (`--install`, `--load`, `--list`, `--search`, `--remove`) |
| `spectre config` | Manage configuration |
| `spectre events` | View system events |
| `spectre daemon` | Manage daemon |
| `spectre logs` | View daemon logs |

### Data Commands
| Command | Description |
|---------|-------------|
| `spectre export` | Export data (`--format json/csv`) |
| `spectre import` | Import data from JSON |
| `spectre report` | Generate reports |

## TUI Dashboard

The enterprise-grade Textual TUI dashboard provides real-time system monitoring:

```bash
spectre dashboard
```

**Features:**
- **7 Tabs**: Dashboard, Agents, Workflows, Security, Logs, Reports, Settings
- **Real-time Metrics**: CPU, Memory, Disk, Network with sparklines (2s refresh)
- **Keyboard Shortcuts**: `1-7` tabs, `q` quit, `r` refresh, `d` dark mode
- **Dark/Light Mode**: Toggle with `d`
- **Interactive**: Navigate with keyboard, view detailed metrics

## Workflows

### Built-in Workflows
| Workflow | Description |
|----------|-------------|
| `morning-startup` | Daily startup: health check, updates, AI status |
| `weekly-maintenance` | Complete weekly system maintenance |
| `security-audit` | Full security audit scan |
| `container-cleanup` | Prune container environments |
| `model-cleanup` | Verify Ollama status and benchmark |
| `shutdown` | Pre-shutdown checks |
| `monthly-optimization` | Comprehensive monthly optimization |
| `dependency-updates` | Check for outdated dependencies |
| `backup` | Backup verification |
| `restore` | Post-restore verification |

### Custom Workflows

Create custom workflows in YAML or JSON:

**YAML format:**
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

**Load and run:**
```bash
spectre workflows --load /path/to/workflows
spectre workflows my-workflow
```

## API Reference

### Bind address and port

The API binds `127.0.0.1:8000` by default. Both halves are overridable, and on a
workstation you usually need to:

| Variable | Default | Meaning |
|----------|---------|---------|
| `SPECTRE_API_HOST` | `127.0.0.1` | Bind address. Loopback is the intended default. |
| `SPECTRE_API_PORT` | `8000` | Bind/published port. |

`8000` is one of the most contested ports on a Linux workstation, and that
collision is not hypothetical: when something unrelated already holds it, the API
is unreachable while the other service answers on the same port. A monitoring
scraper pointed at the wrong port then reads that service's `404` as "the agent is
down", which points debugging at the agent instead of at the port.

Set the port explicitly rather than relying on the default:

```bash
# systemd (see scripts/spectre-api.service — it requires both variables)
install -m 600 /dev/null ~/.config/spectre/spectre.env
printf 'SPECTRE_API_KEY=%s\n'      "$(openssl rand -hex 32)" >> ~/.config/spectre/spectre.env
printf 'SPECTRE_API_HOST=127.0.0.1\nSPECTRE_API_PORT=8106\n'   >> ~/.config/spectre/spectre.env
systemctl --user enable --now spectre-api

# docker compose
SPECTRE_API_PORT=8106 docker compose up -d
```

When you move the port, tell whatever scrapes you. The monitoring suite's
`prometheus/security-metrics-exporter.sh` reads `SPECTRE_AGENT_URL` and defaults
to `http://127.0.0.1:8106`; the two must agree.

### Authentication

**`SPECTRE_API_KEY` is required.** The API refuses to serve when it is unset —
every endpoint, including `/api/health`, `/api/version`, `/api/system/status`
and the dashboard, returns `503`. This is deliberate: the API can run workflows,
write config and prune containers, so it must never fall back to open.

```bash
export SPECTRE_API_KEY="$(openssl rand -hex 32)"
curl -H "X-API-Key: $SPECTRE_API_KEY" http://localhost:8000/api/agents
```

Keys are compared in constant time. `docker-compose.yml` requires the variable
and fails fast if it is absent; the systemd user unit reads it from
`~/.config/spectre/spectre.env` (mode `0600`).

### Custom workflow loading

`POST /api/workflows/load` only accepts directories inside
`~/.config/spectre/workflows`. Widen with `SPECTRE_WORKFLOW_ROOTS`
(`:`-separated) — a request for any other directory is rejected with `400`.

### `GET /api/security/summary` — monitoring contract

This endpoint has an external consumer, so its shape is a contract rather than
an implementation detail. `spectre-system-maintenance-suite` polls it and
republishes the response as Prometheus metrics; do not reshape it without
updating that exporter.

```json
{
  "unresolved_total": 623,
  "unresolved_by_severity": { "critical": 0, "high": 170, "medium": 3, "low": 450 },
  "oldest_unresolved_timestamp": "2026-07-20T00:29:03.657729+00:00",
  "last_scan_timestamp": "2026-10-01T23:38:25.356594+00:00",
  "has_ever_scanned": true
}
```

| Field | Type | Guarantee |
|-------|------|-----------|
| `unresolved_total` | int | Count of unresolved findings. May be `0`. |
| `unresolved_by_severity` | object | Counts keyed by severity. **Keys are sparse** — absent means zero, so a consumer must not assume `critical`/`high`/`medium`/`low` are all present. |
| `oldest_unresolved_timestamp` | string \| null | Aware UTC ISO-8601. `null` when nothing is unresolved. |
| `last_scan_timestamp` | string \| null | Aware UTC ISO-8601, derived from the newest recorded security-agent run — **never** the moment of the request. |
| `has_ever_scanned` | bool | Distinguishes "scanned and found nothing" from "never scanned". |

Two properties the consumer depends on and that must survive refactors:

- **A stale database reports a stale scan.** `last_scan_timestamp` comes from
  recorded data, so serving from an old database reports an old scan time
  rather than claiming a scan just happened.
- **Read-only and derived from records.** It runs no scans and mutates nothing,
  so polling it every few minutes is safe.

It is authenticated like every other endpoint: `401` without a valid
`X-API-Key`, `503` when `SPECTRE_API_KEY` is unset.

### Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard HTML (API key required) |
| `/api/health` | GET | Health check |
| `/api/version` | GET | Version info |
| `/api/agents` | GET | List agents |
| `/api/agents/{agent_name}` | GET | Agent status |
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
| `/api/security/summary` | GET | Current security exposure. [Contract above](#get-apisecuritysummary--monitoring-contract) |
| `/api/reports` | GET | List reports |
| `/api/reports/{report_id}` | GET | Get report |
| `/api/config/{key}` | GET/PUT | Config management |
| `/api/decisions` | GET | List decisions |


## Configuration

Settings are loaded with 4-level priority: Runtime > Project > User > Global

```yaml
# ~/.config/spectre/settings.yaml
profile: laptop
log_level: INFO
ollama:
  url: http://localhost:11434
  benchmark_model: llama3.2:3b
monitoring:
  interval_seconds: 30
  enabled: true
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

## Docker

```bash
# Build and run with docker-compose
docker-compose up -d

# Or build manually
docker build -t spectre .
docker run -p 8000:8000 spectre
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

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## Acknowledgments

- Built with [Typer](https://typer.tiangolo.com/), [Rich](https://rich.readthedocs.io/), [FastAPI](https://fastapi.tiangolo.com/)
- System monitoring via [psutil](https://github.com/giampaolo/psutil)
- Database via [SQLModel](https://sqlmodel.tiangolo.com/)
