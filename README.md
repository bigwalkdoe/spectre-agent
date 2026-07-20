# Spectre

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-189%20passing-brightgreen.svg)](#testing)
[![Code Style](https://img.shields.io/badge/code%20style-ruff-black.svg)](https://github.com/astral-sh/ruff)

**Autonomous AI Engineering Operating System for Fedora Linux**

Spectre monitors, maintains, secures, and manages your Linux workstation through intelligent agents, automated workflows, and a powerful CLI/API/daemon architecture.

## Features

- **8 Intelligent Agents** — Real system integration with psutil, subprocess, and API calls
- **29 CLI Commands** — Complete control from the terminal
- **24 REST API Endpoints** — Programmatic access with API key authentication
- **Custom Workflows** — Load and execute YAML/JSON workflows at runtime
- **Scheduled Tasks** — Cron and interval-based automation
- **Plugin System** — Extensible architecture with manifest-based plugins
- **Interactive Dashboard** — Rich TUI for real-time monitoring
- **Data Import/Export** — JSON and CSV support
- **Docker Support** — Containerized deployment with docker-compose

## Quick Start

### Installation

```bash
# Clone the repository
git clone https://github.com/bigwalkdoe/spectre.git
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

# Run a workflow
spectre workflows morning-startup

# Start the daemon
spectre daemon start
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / API                            │
│  (31 commands, 24 endpoints, TUI dashboard, JSON output)   │
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

### Authentication

Set `SPECTRE_API_KEY` environment variable to enable API key authentication:

```bash
export SPECTRE_API_KEY="your-secret-key"
curl -H "X-API-Key: your-secret-key" http://localhost:8000/api/agents
```

### Endpoints

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
