"""Tests for the workflow engine."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from packages.workflow_engine.engine import (
    WorkflowEngine,
    load_workflow_from_yaml,
    load_workflow_from_json,
    load_workflows_from_dir,
    WORKFLOW_DEFINITIONS,
)


def test_workflow_engine_init() -> None:
    engine = WorkflowEngine()
    assert len(engine.agents) == 8
    assert "linux" in engine.agents
    assert "devops" in engine.agents
    assert "security" in engine.agents
    assert "ai" in engine.agents
    assert "developer" in engine.agents
    assert "monitoring" in engine.agents
    assert "documentation" in engine.agents
    assert "publishing" in engine.agents


def test_available_workflows() -> None:
    engine = WorkflowEngine()
    workflows = engine.get_available_workflows()
    assert len(workflows) == 10
    assert "morning-startup" in workflows
    assert "weekly-maintenance" in workflows
    assert "security-audit" in workflows
    assert "shutdown" in workflows
    assert "monthly-optimization" in workflows


def test_run_morning_startup() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("morning-startup")
    assert result["workflow"] == "morning-startup"
    assert result["status"] in ("success", "failed")
    assert result["duration_ms"] >= 0
    # New format: keys are agent.action
    assert any(k.startswith("linux.") for k in result["details"])
    assert any(k.startswith("ai.") for k in result["details"])


def test_run_weekly_maintenance() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("weekly-maintenance")
    assert result["workflow"] == "weekly-maintenance"
    assert any(k.startswith("linux.") for k in result["details"])
    assert any(k.startswith("devops.") for k in result["details"])
    assert any(k.startswith("security.") for k in result["details"])


def test_run_security_audit() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("security-audit")
    assert result["workflow"] == "security-audit"
    assert any(k.startswith("security.") for k in result["details"])


def test_run_container_cleanup() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("container-cleanup")
    assert result["workflow"] == "container-cleanup"
    assert any(k.startswith("devops.") for k in result["details"])


def test_run_model_cleanup() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("model-cleanup")
    assert result["workflow"] == "model-cleanup"
    assert any(k.startswith("ai.") for k in result["details"])


def test_run_shutdown() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("shutdown")
    assert result["workflow"] == "shutdown"
    assert any(k.startswith("linux.") for k in result["details"])
    assert any(k.startswith("devops.") for k in result["details"])


def test_run_monthly_optimization() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("monthly-optimization")
    assert result["workflow"] == "monthly-optimization"
    assert any(k.startswith("linux.") for k in result["details"])
    assert any(k.startswith("security.") for k in result["details"])
    assert any(k.startswith("developer.") for k in result["details"])


def test_run_dependency_updates() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("dependency-updates")
    assert result["workflow"] == "dependency-updates"
    assert any(k.startswith("developer.") for k in result["details"])


def test_run_backup() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("backup")
    assert result["workflow"] == "backup"


def test_run_restore() -> None:
    engine = WorkflowEngine()
    result = engine.run_workflow("restore")
    assert result["workflow"] == "restore"


def test_unknown_workflow_raises() -> None:
    engine = WorkflowEngine()
    with pytest.raises(ValueError, match="Unknown workflow"):
        engine.run_workflow("nonexistent")


def test_get_agents() -> None:
    engine = WorkflowEngine()
    agents = engine.get_agents()
    assert isinstance(agents, dict)
    assert len(agents) == 8


def test_get_workflow_definitions() -> None:
    engine = WorkflowEngine()
    defs = engine.get_workflow_definitions()
    assert "morning-startup" in defs
    assert defs["morning-startup"].description != ""
    assert len(defs["morning-startup"].steps) > 0


def test_weekly_maintenance_alias() -> None:
    """weekly-maintenance should work (the old 'weekly' alias is removed)."""
    engine = WorkflowEngine()
    result = engine.run_workflow("weekly-maintenance")
    assert result["workflow"] == "weekly-maintenance"


def test_security_audit_full_name() -> None:
    """security-audit should work (the old 'security' alias is removed)."""
    engine = WorkflowEngine()
    result = engine.run_workflow("security-audit")
    assert result["workflow"] == "security-audit"


# ── Integration tests for custom workflows ──────────────────────────────────


def test_load_workflow_from_yaml() -> None:
    """Test loading a workflow from YAML file."""
    yaml_content = """
name: test-yaml-workflow
description: Test workflow from YAML
steps:
  - agent: linux
    action: system-health-check
  - agent: monitoring
    action: collect-metrics
"""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        wf = load_workflow_from_yaml(f.name)

    assert wf is not None
    assert wf.name == "test-yaml-workflow"
    assert len(wf.steps) == 2
    assert wf.steps[0].agent == "linux"
    assert wf.steps[0].action == "system-health-check"
    assert wf.steps[1].agent == "monitoring"
    assert wf.steps[1].action == "collect-metrics"


def test_load_workflow_from_json() -> None:
    """Test loading a workflow from JSON file."""
    import json

    json_data = {
        "name": "test-json-workflow",
        "description": "Test workflow from JSON",
        "steps": [
            {"agent": "security", "action": "selinux-audit"},
            {"agent": "security", "action": "firewall-audit"},
        ],
    }

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(json_data, f)
        f.flush()
        wf = load_workflow_from_json(f.name)

    assert wf is not None
    assert wf.name == "test-json-workflow"
    assert len(wf.steps) == 2
    assert wf.steps[0].agent == "security"
    assert wf.steps[0].action == "selinux-audit"


def test_load_workflows_from_dir() -> None:
    """Test loading multiple workflows from a directory."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create two workflow files
        yaml_content = """
name: dir-workflow-1
description: First workflow
steps:
  - agent: linux
    action: system-health-check
"""
        json_content = """
{
    "name": "dir-workflow-2",
    "description": "Second workflow",
    "steps": [
        {"agent": "monitoring", "action": "collect-metrics"}
    ]
}
"""

        with open(Path(tmpdir) / "wf1.yaml", "w") as f:
            f.write(yaml_content)
        with open(Path(tmpdir) / "wf2.json", "w") as f:
            f.write(json_content)

        workflows = load_workflows_from_dir(tmpdir)
        assert len(workflows) == 2
        assert "dir-workflow-1" in workflows
        assert "dir-workflow-2" in workflows


def test_engine_load_workflows() -> None:
    """Test WorkflowEngine.load_workflows method."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_content = """
name: engine-loaded-workflow
description: Loaded via engine
steps:
  - agent: linux
    action: dnf-check-update
"""
        with open(Path(tmpdir) / "custom.yaml", "w") as f:
            f.write(yaml_content)

        engine = WorkflowEngine()
        count = engine.load_workflows(tmpdir)
        assert count == 1
        assert "engine-loaded-workflow" in engine.custom_workflows
        assert "engine-loaded-workflow" in engine.get_available_workflows()


def test_engine_register_workflow() -> None:
    """Test WorkflowEngine.register_workflow method."""
    from packages.workflow_engine.engine import WorkflowDefinition, Step

    engine = WorkflowEngine()
    custom_wf = WorkflowDefinition(
        name="registered-workflow",
        description="Registered via API",
        steps=[Step(agent="linux", action="system-health-check")],
    )
    engine.register_workflow(custom_wf)
    assert "registered-workflow" in engine.custom_workflows
    assert "registered-workflow" in engine.get_available_workflows()


def test_custom_workflow_execution() -> None:
    """Test executing a custom loaded workflow."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_content = """
name: custom-exec-workflow
description: Custom workflow for execution test
steps:
  - agent: linux
    action: system-health-check
  - agent: monitoring
    action: collect-metrics
"""
        with open(Path(tmpdir) / "exec.yaml", "w") as f:
            f.write(yaml_content)

        engine = WorkflowEngine()
        engine.load_workflows(tmpdir)
        result = engine.run_workflow("custom-exec-workflow")

        assert result["workflow"] == "custom-exec-workflow"
        assert result["status"] in ("success", "failed")
        assert any(k.startswith("linux.") for k in result["details"])
        assert any(k.startswith("monitoring.") for k in result["details"])


def test_workflow_with_retries() -> None:
    """Test workflow step with max_retries."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_content = """
name: retry-workflow
description: Workflow with retries
steps:
  - agent: linux
    action: system-health-check
    max_retries: 2
    retry_delay_ms: 100
"""
        with open(Path(tmpdir) / "retry.yaml", "w") as f:
            f.write(yaml_content)

        engine = WorkflowEngine()
        engine.load_workflows(tmpdir)
        result = engine.run_workflow("retry-workflow")

        assert result["workflow"] == "retry-workflow"
        assert result["status"] in ("success", "failed")


def test_workflow_continue_on_failure() -> None:
    """Test workflow with continue_on_failure."""
    with tempfile.TemporaryDirectory() as tmpdir:
        yaml_content = """
name: continue-on-fail
description: Continue on failure
continue_on_failure: true
steps:
  - agent: linux
    action: system-health-check
  - agent: nonexistent-agent
    action: some-action
  - agent: monitoring
    action: collect-metrics
"""
        with open(Path(tmpdir) / "continue.yaml", "w") as f:
            f.write(yaml_content)

        engine = WorkflowEngine()
        engine.load_workflows(tmpdir)
        result = engine.run_workflow("continue-on-fail")

        assert result["workflow"] == "continue-on-fail"
        # Should complete all steps despite failure
        assert "linux.system-health-check" in result["details"]
        assert "monitoring.collect-metrics" in result["details"]


def test_workflow_definition_builtins() -> None:
    """Test all built-in workflow definitions are valid."""
    for name, wf in WORKFLOW_DEFINITIONS.items():
        assert wf.name == name
        assert wf.description != ""
        assert len(wf.steps) > 0
        for step in wf.steps:
            assert step.agent != ""
            assert step.action != ""
            assert step.max_retries >= 0
            assert step.retry_delay_ms >= 0
