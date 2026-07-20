# Spectre Plugin System

## Overview

Spectre supports dynamic plugins that extend CLI commands, workflows, and event handling without modifying core code.

## Plugin Location

Plugins are loaded from `~/.config/spectre/plugins/` by default. Configure a custom path in `settings.yaml`:

```yaml
plugins_dir: "/path/to/plugins"
```

## Creating a Plugin

A plugin is a Python file containing a subclass of `BasePlugin`:

```python
# ~/.config/spectre/plugins/my_plugin.py

from packages.plugins.loader import BasePlugin


class MyPlugin(BasePlugin):
    def register_commands(self) -> list[dict]:
        """Register custom CLI commands."""
        return [
            {
                "name": "my-command",
                "help": "A custom command added by my plugin",
                "callback": self.my_command,
            }
        ]

    def register_workflows(self) -> dict[str, list[str]]:
        """Register custom workflows."""
        return {
            "my-workflow": ["action-1", "action-2"],
        }

    def register_listeners(self) -> dict[str, callable]:
        """Register event listeners."""
        return {
            "security.incident": self.on_security_incident,
        }

    def my_command(self) -> None:
        print("Hello from my plugin!")

    def on_security_incident(self, data: dict) -> None:
        print(f"Security incident: {data}")
```

## BasePlugin Interface

```python
class BasePlugin:
    def __init__(self, context: dict[str, Any]):
        self.context = context

    def register_commands(self) -> list[dict[str, Any]]:
        """Return list of CLI command definitions."""
        return []

    def register_workflows(self) -> dict[str, list[str]]:
        """Return dict of workflow definitions: {name: [actions]}."""
        return {}

    def register_listeners(self) -> dict[str, Any]:
        """Return dict of event listeners: {event_name: callback}."""
        return {}
```

## Command Registration

Each command dict should contain:

| Key | Type | Required | Description |
|-----|------|----------|-------------|
| `name` | str | Yes | Command name (used as `spectre <name>`) |
| `help` | str | No | Help text |
| `callback` | callable | Yes | Function to execute |
| `arguments` | list | No | Argument definitions |
| `options` | list | No | Option definitions |

## Workflow Registration

Workflows map a name to a list of action strings:

```python
def register_workflows(self) -> dict[str, list[str]]:
    return {
        "my-custom-workflow": ["system-health-check", "dnf-check-update"],
    }
```

## Event Listeners

Subscribe to events published by agents and the workflow engine:

```python
def register_listeners(self) -> dict[str, callable]:
    return {
        "agent.completed": self.on_agent_done,
        "workflow.started": self.on_workflow_start,
    }
```

### Available Events

| Event | Data |
|-------|------|
| `system.health` | Health check results |
| `agent.started` | Agent name and action |
| `agent.completed` | Agent name, action, result |
| `agent.failed` | Agent name, action, error |
| `workflow.started` | Workflow name |
| `workflow.completed` | Workflow name, status |
| `security.incident` | Severity, rule, message |
| `maintenance.started` | Agent, action |
| `maintenance.completed` | Agent, action, result |
| `config.changed` | Key, old value, new value |

## Loading Plugins

Plugins are loaded automatically by the `PluginLoader`:

```python
from packages.plugins.loader import PluginLoader

loader = PluginLoader()
plugins = loader.load_plugins(context={"settings": settings})
```

## Example Plugin

See `examples/simple_plugin.py` for a complete working example.
