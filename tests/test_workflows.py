"""Tests for the workflow engine."""

from __future__ import annotations

import pytest

from packages.workflow_engine.engine import WorkflowEngine


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
