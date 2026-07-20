"""Workflow Engine — Data-driven workflow execution with ServiceBus and EventBus integration."""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from packages.core.agent import AgentContext
from packages.core.event_bus import EventBus
from packages.core.service_bus import ServiceBus
from packages.memory.db import WorkflowRun, save_workflow_run

logger = logging.getLogger(__name__)


@dataclass
class Step:
    """A single step in a workflow."""

    agent: str
    action: str
    params: dict[str, Any] = field(default_factory=dict)
    condition: Callable[[], bool] | None = None
    max_retries: int = 0
    retry_delay_ms: int = 1000
    rollback: str | None = None
    on_success: str | None = None  # Event to publish on success
    on_failure: str | None = None  # Event to publish on failure


@dataclass
class WorkflowDefinition:
    """Declarative workflow definition."""

    name: str
    description: str
    steps: list[Step]
    continue_on_failure: bool = False
    on_complete: str | None = None  # Event to publish on workflow completion


# ── Workflow Definitions ──────────────────────────────────────────────────

WORKFLOW_DEFINITIONS: dict[str, WorkflowDefinition] = {
    "morning-startup": WorkflowDefinition(
        name="morning-startup",
        description="Daily startup: health check, updates, AI status",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="linux", action="dnf-check-update"),
            Step(agent="ai", action="ollama-ping"),
        ],
    ),
    "weekly-maintenance": WorkflowDefinition(
        name="weekly-maintenance",
        description="Complete weekly system maintenance",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="linux", action="dnf-check-update"),
            Step(agent="linux", action="flatpak-prune"),
            Step(agent="linux", action="journal-cleanup"),
            Step(agent="devops", action="podman-prune"),
            Step(agent="devops", action="docker-prune"),
            Step(agent="security", action="ports-audit"),
            Step(agent="security", action="secrets-scan"),
        ],
    ),
    "security-audit": WorkflowDefinition(
        name="security-audit",
        description="Full security audit scan",
        steps=[
            Step(agent="security", action="selinux-audit"),
            Step(agent="security", action="firewall-audit"),
            Step(agent="security", action="ports-audit"),
            Step(agent="security", action="secrets-scan"),
            Step(agent="security", action="ssh-audit"),
        ],
    ),
    "container-cleanup": WorkflowDefinition(
        name="container-cleanup",
        description="Prune container environments",
        steps=[
            Step(agent="devops", action="podman-prune"),
            Step(agent="devops", action="docker-prune"),
        ],
    ),
    "model-cleanup": WorkflowDefinition(
        name="model-cleanup",
        description="Verify Ollama status and benchmark",
        steps=[
            Step(agent="ai", action="ollama-ping"),
            Step(agent="ai", action="list-models"),
            Step(agent="ai", action="benchmark-model"),
        ],
    ),
    "shutdown": WorkflowDefinition(
        name="shutdown",
        description="Pre-shutdown checks",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="devops", action="podman-status"),
            Step(agent="devops", action="docker-status"),
        ],
    ),
    "monthly-optimization": WorkflowDefinition(
        name="monthly-optimization",
        description="Comprehensive monthly optimization",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="linux", action="dnf-check-update"),
            Step(agent="linux", action="flatpak-prune"),
            Step(agent="linux", action="journal-cleanup"),
            Step(agent="devops", action="podman-prune"),
            Step(agent="devops", action="docker-prune"),
            Step(agent="security", action="selinux-audit"),
            Step(agent="security", action="firewall-audit"),
            Step(agent="security", action="ports-audit"),
            Step(agent="developer", action="dependency-audit"),
        ],
    ),
    "dependency-updates": WorkflowDefinition(
        name="dependency-updates",
        description="Check for outdated dependencies",
        steps=[
            Step(agent="developer", action="dependency-audit"),
            Step(agent="developer", action="git-status"),
        ],
    ),
    "backup": WorkflowDefinition(
        name="backup",
        description="Backup configuration and database",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="developer", action="git-status"),
        ],
    ),
    "restore": WorkflowDefinition(
        name="restore",
        description="Verify system state after restore",
        steps=[
            Step(agent="linux", action="system-health-check"),
            Step(agent="devops", action="podman-status"),
            Step(agent="devops", action="docker-status"),
        ],
    ),
}

# ── Agent Factory Registry ────────────────────────────────────────────────

_AGENT_FACTORIES: dict[str, type] = {}


def register_agent_factory(name: str, cls: type) -> None:
    """Register an agent class for lazy instantiation."""
    _AGENT_FACTORIES[name] = cls


def _register_default_factories() -> None:
    """Register all built-in agent factories."""
    if _AGENT_FACTORIES:
        return
    from packages.ai_agent.agent import AIAgent
    from packages.developer_agent.agent import DeveloperAgent
    from packages.devops_agent.agent import DevOpsAgent
    from packages.documentation_agent.agent import DocumentationAgent
    from packages.linux_agent.agent import LinuxAgent
    from packages.monitoring_agent.agent import MonitoringAgent
    from packages.publishing_agent.agent import PublishingAgent
    from packages.security_agent.agent import SecurityAgent

    register_agent_factory("linux", LinuxAgent)
    register_agent_factory("devops", DevOpsAgent)
    register_agent_factory("security", SecurityAgent)
    register_agent_factory("ai", AIAgent)
    register_agent_factory("developer", DeveloperAgent)
    register_agent_factory("monitoring", MonitoringAgent)
    register_agent_factory("documentation", DocumentationAgent)
    register_agent_factory("publishing", PublishingAgent)


# ── Custom Workflow Loading ───────────────────────────────────────────────


def load_workflow_from_yaml(path: str | Path) -> WorkflowDefinition | None:
    """Load a workflow definition from a YAML file.

    Example YAML format:
    ```yaml
    name: my-workflow
    description: My custom workflow
    continue_on_failure: false
    on_complete: workflow.custom.completed
    steps:
      - agent: linux
        action: system-health-check
      - agent: security
        action: ports-audit
        max_retries: 2
        on_success: security.audit.passed
    ```
    """
    from pathlib import Path

    import yaml

    filepath = Path(path)
    if not filepath.is_file():
        logger.warning("Workflow file not found: %s", filepath)
        return None

    try:
        with open(filepath, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return _parse_workflow_definition(data)
    except Exception:
        logger.exception("Failed to load workflow from %s", filepath)
        return None


def load_workflow_from_json(path: str | Path) -> WorkflowDefinition | None:
    """Load a workflow definition from a JSON file."""
    from pathlib import Path

    filepath = Path(path)
    if not filepath.is_file():
        logger.warning("Workflow file not found: %s", filepath)
        return None

    try:
        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)
        return _parse_workflow_definition(data)
    except Exception:
        logger.exception("Failed to load workflow from %s", filepath)
        return None


def _parse_workflow_definition(data: dict[str, Any]) -> WorkflowDefinition | None:
    """Parse a workflow definition from a dict."""
    try:
        steps = []
        for step_data in data.get("steps", []):
            steps.append(Step(
                agent=step_data["agent"],
                action=step_data["action"],
                params=step_data.get("params", {}),
                max_retries=step_data.get("max_retries", 0),
                retry_delay_ms=step_data.get("retry_delay_ms", 1000),
                rollback=step_data.get("rollback"),
                on_success=step_data.get("on_success"),
                on_failure=step_data.get("on_failure"),
            ))

        return WorkflowDefinition(
            name=data["name"],
            description=data.get("description", ""),
            steps=steps,
            continue_on_failure=data.get("continue_on_failure", False),
            on_complete=data.get("on_complete"),
        )
    except (KeyError, TypeError) as e:
        logger.warning("Invalid workflow definition: %s", e)
        return None


def load_workflows_from_dir(directory: str | Path) -> dict[str, WorkflowDefinition]:
    """Load all workflow definitions from a directory (YAML and JSON files)."""
    from pathlib import Path

    dir_path = Path(directory)
    if not dir_path.is_dir():
        return {}

    workflows = {}
    for filepath in dir_path.glob("*.yaml"):
        wf = load_workflow_from_yaml(filepath)
        if wf:
            workflows[wf.name] = wf

    for filepath in dir_path.glob("*.yml"):
        wf = load_workflow_from_yaml(filepath)
        if wf:
            workflows[wf.name] = wf

    for filepath in dir_path.glob("*.json"):
        wf = load_workflow_from_json(filepath)
        if wf:
            workflows[wf.name] = wf

    return workflows


class WorkflowEngine:
    """Executes workflows via ServiceBus agent resolution with EventBus integration.

    Agents are resolved from the ServiceBus if available,
    otherwise instantiated directly from the factory registry.
    Events are published before/after steps for plugin hooks.
    Custom workflows can be loaded from YAML/JSON files.
    """

    def __init__(
        self,
        config: dict[str, Any] | None = None,
        service_bus: ServiceBus | None = None,
        event_bus: EventBus | None = None,
        workflows_dir: str | Path | None = None,
    ):
        self.config = config or {}
        self.service_bus = service_bus or ServiceBus()
        self.event_bus = event_bus or EventBus()
        _register_default_factories()
        self.agents: dict[str, Any] = self._initialize_agents()
        self.custom_workflows: dict[str, WorkflowDefinition] = {}

        # Load custom workflows from directory
        if workflows_dir:
            self.load_workflows(workflows_dir)

    def _initialize_agents(self) -> dict[str, Any]:
        """Create and register all agents with the ServiceBus."""
        agents: dict[str, Any] = {}
        context = AgentContext(service_bus=self.service_bus)

        for name, cls in _AGENT_FACTORIES.items():
            agent = cls(config=self.config, context=context)
            agent.initialize()
            agents[name] = agent
            # Register with service bus
            self.service_bus.register_service(name, "agent", agent, actions=getattr(agent, 'tools', {}).keys() if hasattr(agent, 'tools') else [])

        return agents

    def resolve_agent(self, name: str) -> Any | None:
        """Resolve an agent by name, checking ServiceBus first."""
        # Try ServiceBus first
        agent = self.service_bus.get_service(name)
        if agent:
            return agent
        # Fallback to local registry
        return self.agents.get(name)

    def load_workflows(self, directory: str | Path) -> int:
        """Load custom workflows from a directory. Returns count loaded."""
        loaded = load_workflows_from_dir(directory)
        self.custom_workflows.update(loaded)
        logger.info("Loaded %d custom workflows from %s", len(loaded), directory)
        return len(loaded)

    def register_workflow(self, definition: WorkflowDefinition) -> None:
        """Register a custom workflow definition."""
        self.custom_workflows[definition.name] = definition
        logger.info("Registered custom workflow: %s", definition.name)

    def get_available_workflows(self) -> list[str]:
        """Return a list of all available workflow names (built-in + custom)."""
        all_workflows = set(WORKFLOW_DEFINITIONS.keys())
        all_workflows.update(self.custom_workflows.keys())
        return sorted(all_workflows)

    def get_workflow_definitions(self) -> dict[str, WorkflowDefinition]:
        """Return all workflow definitions (built-in + custom)."""
        all_defs = dict(WORKFLOW_DEFINITIONS)
        all_defs.update(self.custom_workflows)
        return all_defs

    def get_agents(self) -> dict[str, Any]:
        """Return the agent instances."""
        return dict(self.agents)

    def run_workflow(self, name: str) -> dict[str, Any]:
        """Execute a workflow with step-level conditions, retries, rollback, and events."""
        # Check built-in workflows first, then custom
        definition = WORKFLOW_DEFINITIONS.get(name) or self.custom_workflows.get(name)
        if not definition:
            raise ValueError(f"Unknown workflow: {name}")

        start_time = time.monotonic()
        step_results: dict[str, Any] = {}
        status = "success"
        failed_steps: list[str] = []

        # Publish workflow started event (sync wrapper)
        self._publish_event("workflow.started", {"workflow": name})

        for i, step in enumerate(definition.steps):
            step_key = f"{step.agent}.{step.action}"

            # Publish step started event
            self._publish_event("workflow.step.started", {"workflow": name, "step": step_key, "agent": step.agent, "action": step.action})

            # Check condition
            if step.condition and not step.condition():
                step_results[step_key] = {"status": "skipped", "reason": "condition_not_met"}
                self._publish_event("workflow.step.skipped", {"workflow": name, "step": step_key})
                continue

            # Resolve agent from ServiceBus or local registry
            agent = self.resolve_agent(step.agent)
            if not agent:
                step_results[step_key] = {"status": "failed", "error": f"Agent '{step.agent}' not found"}
                failed_steps.append(step_key)
                self._publish_event("workflow.step.failed", {"workflow": name, "step": step_key, "error": f"Agent '{step.agent}' not found"})
                if not definition.continue_on_failure:
                    status = "failed"
                    break
                continue

            # Execute with retries
            attempts = 0
            success = False
            last_error = None

            while attempts <= step.max_retries:
                try:
                    result = agent.execute([step.action])
                    step_results[step_key] = result.get(step.action, {"status": "unknown"})
                    if step_results[step_key].get("status") != "failed":
                        success = True
                        break
                except Exception as e:
                    last_error = str(e)
                    step_results[step_key] = {"status": "failed", "error": last_error}

                attempts += 1
                if attempts <= step.max_retries:
                    time.sleep(step.retry_delay_ms / 1000)

            if success:
                # Publish step completed event
                self._publish_event("workflow.step.completed", {"workflow": name, "step": step_key, "result": step_results[step_key]})
                # Publish custom success event
                if step.on_success:
                    self._publish_event(step.on_success, {"workflow": name, "step": step_key, "result": step_results[step_key]})
            else:
                failed_steps.append(step_key)
                status = "failed"
                # Publish step failed event
                self._publish_event("workflow.step.failed", {"workflow": name, "step": step_key, "error": last_error})
                # Publish custom failure event
                if step.on_failure:
                    self._publish_event(step.on_failure, {"workflow": name, "step": step_key, "error": last_error})

                # Run rollback if defined
                if step.rollback:
                    try:
                        rollback_agent = self.resolve_agent(step.agent)
                        if rollback_agent:
                            rollback_agent.execute([step.rollback])
                            self._publish_event("workflow.step.rollback", {"workflow": name, "step": step_key})
                    except Exception:
                        pass

                if not definition.continue_on_failure:
                    break

        duration_ms = int((time.monotonic() - start_time) * 1000)

        # Persist
        try:
            save_workflow_run(
                WorkflowRun(
                    workflow=name,
                    status=status,
                    duration_ms=duration_ms,
                    details=json.dumps(step_results, default=str),
                )
            )
        except Exception:
            pass

        # Publish workflow completed event
        self._publish_event("workflow.completed", {
            "workflow": name,
            "status": status,
            "duration_ms": duration_ms,
            "failed_steps": failed_steps,
        })
        # Publish custom completion event
        if definition.on_complete:
            self._publish_event(definition.on_complete, {"workflow": name, "status": status})

        return {
            "workflow": name,
            "status": status,
            "duration_ms": duration_ms,
            "failed_steps": failed_steps,
            "details": step_results,
        }

    def _publish_event(self, event: str, data: Any = None) -> None:
        """Publish an event synchronously, logging any errors."""
        try:
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.ensure_future(self.event_bus.publish(event, data))
            else:
                loop.run_until_complete(self.event_bus.publish(event, data))
        except RuntimeError:
            try:
                loop = asyncio.new_event_loop()
                loop.run_until_complete(self.event_bus.publish(event, data))
                loop.close()
            except Exception:
                logger.debug("Failed to publish event: %s", event)

    def register_plugin_hooks(self, plugin_loader: Any) -> None:
        """Register plugin event listeners with the EventBus.

        Plugins can subscribe to workflow events via their register_listeners().
        """
        for plugin in plugin_loader.plugins:
            listeners = plugin.register_listeners()
            for event, callback in listeners.items():
                self.event_bus.subscribe(event, callback)
                logger.debug("Plugin %s subscribed to event: %s", plugin.manifest.name, event)
