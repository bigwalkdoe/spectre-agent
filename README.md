# Spectre

Autonomous AI Engineering Operating System for Fedora Linux. Monitors, maintains, secures, and manages your workstation through agents, workflows, plugins, and a CLI/API/daemon.

## Quickstart

```bash
pip install -e ".[dev]"

# Run system diagnostics
spectre doctor

# Show system status
spectre status

# Run a workflow
spectre workflows morning-startup

# View Kernel status
spectre kernel status

# Inspect ServiceBus
spectre service-bus --list

# Show core components
spectre core
```

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                        CLI / API                            │
│           (doctor, kernel, service-bus, core)               │
├─────────────────────────────────────────────────────────────┤
│                     WorkflowEngine                          │
│    (ServiceBus resolution + EventBus event publishing)      │
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

## CLI Commands

| Command | Description |
|---------|-------------|
| `spectre doctor` | Run system diagnostics and verify Kernel + ServiceBus health |
| `spectre health` | Display system health metrics |
| `spectre status` | Show overall system status |
| `spectre monitor` | Display live system metrics |
| `spectre update` | Check for system updates |
| `spectre clean` | Clean system caches and unused packages |
| `spectre repair` | Attempt system repair and health restoration |
| `spectre optimize` | Run system optimization workflows |
| `spectre security` | Security status and auditing |
| `spectre services` | Manage systemd services |
| `spectre containers` | List and manage containers |
| `spectre models` | Manage AI models (Ollama) |
| `spectre workflows` | Execute or list maintenance workflows |
| `spectre backup` | Backup configuration and data |
| `spectre restore` | Restore configuration and data |
| `spectre report` | Generate system reports |
| `spectre kernel` | Manage the Spectre Kernel lifecycle |
| `spectre service-bus` | Inspect the Service Bus |
| `spectre core` | Show Spectre Core status |

## Workflows

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

## Configuration

Settings are loaded with 4-level priority: Runtime > Project > User > Global

```yaml
# ~/.config/spectre/settings.yaml
profile: laptop
log_level: INFO
ollama_url: http://localhost:11434
monitoring_interval: 30
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/health` | GET | Health check |
| `/api/agents` | GET | List agents |
| `/api/agents/{name}` | GET | Agent status |
| `/api/workflows` | GET | List workflows |
| `/api/workflows/{name}` | POST | Run workflow |
| `/api/workflows/history` | GET | Workflow history |
| `/api/system/status` | GET | System status |
| `/api/core/kernel` | GET | Kernel status |
| `/api/core/kernel/start` | POST | Start Kernel |
| `/api/core/kernel/stop` | POST | Stop Kernel |
| `/api/core/service-bus` | GET | ServiceBus status |
| `/api/reports` | GET | List reports |
| `/api/config/{key}` | GET | Get config |
| `/api/config/{key}` | PUT | Set config |
| `/api/decisions` | GET | List decisions |

## Database

SQLite at `~/.config/spectre/memory.db` with 12 tables:

- `SystemMetric` — CPU, RAM, disk, battery, temperature history
- `MaintenanceRecord` — Agent action results
- `SecurityIncident` — Security findings
- `Configuration` — Key-value config storage
- `Report` — Generated reports
- `WorkflowRun` — Workflow execution history
- `Decision` — Decision audit log
- `KVStore` — General key-value store
- `Machine` — Machine identity and metadata
- `AgentRecord` — Agent execution audit trail
- `PluginRecord` — Plugin lifecycle tracking
- `EventLog` — System event log
