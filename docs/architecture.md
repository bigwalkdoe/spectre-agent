# Spectre Architecture

## Overview

Spectre follows a modular, agent-based architecture with a central Kernel, DI container, and ServiceBus for inter-agent communication. Each capability is encapsulated in an independent agent that implements a standard lifecycle interface.

## Directory Structure

```
spectre/
├── packages/                    # Core libraries
│   ├── core/                    # Base classes and infrastructure
│   │   ├── agent.py             # BaseAgent ABC + AgentContext
│   │   ├── kernel.py            # Kernel bootstrap, DI, lifecycle
│   │   ├── config.py            # 4-level config hierarchy
│   │   ├── service_bus.py       # Inter-agent communication, persistent registry
│   │   ├── event_bus.py         # Pub/sub event system
│   │   └── scheduler.py         # Task scheduler
│   ├── config/                  # Configuration management
│   │   └── settings.py          # YAML settings with Pydantic
│   ├── memory/                  # Persistent storage
│   │   └── db.py                # SQLite via SQLModel (12 tables)
│   ├── plugins/                 # Plugin system
│   │   └── loader.py            # Manifest, permissions, hooks, ServiceBus registration
│   ├── workflow_engine/         # Workflow orchestration
│   │   └── engine.py            # Data-driven workflows via ServiceBus, custom workflow loading
│   ├── linux_agent/             # Linux maintenance
│   ├── devops_agent/            # Container management
│   ├── security_agent/          # Security auditing
│   ├── ai_agent/                # AI model management
│   ├── developer_agent/         # Development tools
│   ├── monitoring_agent/        # System metrics
│   ├── documentation_agent/     # Documentation
│   └── publishing_agent/        # Release management
├── apps/                        # Application interfaces
│   ├── cli/                     # Command-line interface
│   │   └── main.py              # 23 CLI commands (incl. kernel, service-bus, core, plugins, workflows --load, config, events)
│   ├── api/                     # REST API
│   │   └── main.py              # FastAPI backend (19 endpoints incl. core, events, workflows/load)
│   └── daemon/                  # Background service
│       └── main.py              # Kernel-based daemon
├── config/                      # Configuration files
├── tests/                       # Test suite (170 tests)
├── docs/                        # Documentation
└── scripts/                     # Installation and utilities
```

## Core Components

### Kernel (`packages/core/kernel.py`)

The Kernel is the central bootstrap and lifecycle manager:

```python
kernel = Kernel()
kernel.register_service("my_service", instance)
kernel.start()  # starts scheduler, publishes SystemStarted
kernel.stop()   # runs shutdown hooks, publishes SystemStopped
```

- **DI Container** — Register and resolve services by name
- **Lifecycle Management** — Signal handling, startup/shutdown hooks
- **Event Publishing** — SystemStarted/SystemStopped events
- **Scheduler Integration** — Built-in TaskScheduler

### ServiceBus (`packages/core/service_bus.py`)

Agents communicate only through the ServiceBus — no direct coupling:

```python
bus = ServiceBus()
bus.register_service("linux", "agent", linux_agent, actions=["health", "update"])
bus.register_request_handler("security.scan", handler)
bus.subscribe("system.health", callback)
bus.publish("system.health", {"status": "ok"})
```

- **Service Registration** — Agents register during `initialize()`
- **Request/Response** — Synchronous agent-to-agent calls
- **Publish/Subscribe** — Loose-coupled event messaging

### 4-Level Config (`packages/core/config.py`)

Configuration priority: Runtime > Project > User > Global

```python
from packages.core.config import load_config
config = load_config()  # merges all levels
```

## Agent Lifecycle

Every agent implements the same interface:

```python
class BaseAgent(ABC):
    def initialize(self) -> None: ...
    def plan(self) -> list[str]: ...
    def execute(self, plan: list[str]) -> dict[str, Any]: ...
    def observe(self) -> dict[str, Any]: ...
    def verify(self) -> bool: ...
    def report(self, results: dict[str, Any]) -> str: ...
    def recover(self, error: Exception) -> bool: ...
    def shutdown(self) -> None: ...
```

Agents accept an `AgentContext` with access to Kernel and ServiceBus:

```python
agent = LinuxAgent(config=config, context=AgentContext(service_bus=bus))
agent.initialize()  # registers with ServiceBus
```

## Data Flow

```
CLI/API Request
    ↓
Kernel → ServiceBus → WorkflowEngine
    ↓
ServiceBus.resolve(agent_name)
    ↓
Agent.execute([action]) → Agent.verify()
    ↓
Memory (SQLite) ← Results persisted
    ↓
Response to caller
```

## Workflow Engine

Data-driven workflows with step-level conditions, retries, and rollback:

```python
@dataclass
class Step:
    agent: str
    action: str
    condition: Callable[[], bool] | None = None
    max_retries: int = 0
    rollback: str | None = None

engine = WorkflowEngine(config=config, service_bus=bus)
result = engine.run_workflow("morning-startup")
# Agents resolved from ServiceBus, not direct references

# Custom workflow loading
engine.load_workflows("/path/to/workflows")  # Load from YAML/JSON
wf = WorkflowDefinition(name="custom", steps=[Step(agent="linux", action="check")])
engine.register_workflow(wf)  # Register at runtime

# Workflow definitions available via API
defs = engine.get_workflow_definitions()
```

### Custom Workflow Loading

Load workflows at runtime from YAML or JSON files:

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

**JSON format:**
```json
{
  "name": "my-workflow",
  "description": "Custom workflow",
  "steps": [
    {"agent": "linux", "action": "system-health-check"}
  ]
}
```

**CLI usage:**
```bash
spectre workflows --load /path/to/workflows  # Load from directory
spectre workflows --definitions               # Show all definitions
spectre workflows --definitions --name my-wf  # Show specific definition
```

**API usage:**
```
GET  /api/workflows/definitions    # All definitions
POST /api/workflows/load?directory=/path
POST /api/workflows/my-workflow    # Run workflow
```

## Configuration Management

Spectre supports runtime configuration management via CLI and API:

**CLI commands:**
```bash
spectre config --show          # Display current configuration
spectre config --get log_level # Read a specific key
spectre config --set log_level --value DEBUG  # Set a key-value pair
```

**API endpoints:**
```
GET  /api/config/{key}         # Read config value
PUT  /api/config/{key}?value=X # Set config value
```

Configuration is stored in the database and supports profiles (default, production, etc.).

## Event System

The `EventBus` enables loose coupling between agents, with events persisted to the database:

```python
bus = EventBus()
bus.subscribe("security.incident", handler)
await bus.publish("security.incident", {"severity": "high"})

# Events stored in EventLog table for querying
from packages.memory.db import get_events
events = get_events(event_type="security.incident", limit=10)
```

**CLI usage:**
```bash
spectre events                        # Show recent events
spectre events --type workflow.started # Filter by type
spectre events --limit 50             # Limit results
```

**API usage:**
```
GET /api/events                       # All recent events
GET /api/events?event_type=workflow   # Filter by type
GET /api/events?source=kernel         # Filter by source
```

## Scheduling

The `TaskScheduler` supports both cron expressions and interval syntax:

```python
scheduler = TaskScheduler()
scheduler.add_task("health", "every 30m", check_health)
scheduler.add_task("backup", "0 2 * * *", run_backup)
scheduler.start()
```

## Database Schema

SQLite at `~/.config/spectre/memory.db`:

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

## Design Principles

- **Local-first** — Everything runs on your machine
- **Offline-capable** — No external services required
- **Modular** — Add capabilities without modifying core
- **Observable** — All actions logged and queryable
- **Secure by default** — Agents run with minimal privileges
- **Decoupled** — Agents communicate only through ServiceBus
