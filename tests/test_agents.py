"""Tests for all agents."""

from __future__ import annotations

from packages.ai_agent.agent import AIAgent
from packages.core.agent import BaseAgent
from packages.developer_agent.agent import DeveloperAgent
from packages.devops_agent.agent import DevOpsAgent
from packages.documentation_agent.agent import DocumentationAgent
from packages.linux_agent.agent import LinuxAgent
from packages.monitoring_agent.agent import MonitoringAgent
from packages.publishing_agent.agent import PublishingAgent
from packages.security_agent.agent import SecurityAgent

# ── BaseAgent ─────────────────────────────────────────────────────────────────


def test_base_agent_is_abstract() -> None:
    """BaseAgent cannot be instantiated directly."""
    import pytest
    with pytest.raises(TypeError):
        BaseAgent("test")


def test_agent_lifecycle() -> None:
    """All agents implement the full lifecycle interface."""
    agents = [
        LinuxAgent, DevOpsAgent, SecurityAgent, AIAgent,
        DeveloperAgent, MonitoringAgent, DocumentationAgent, PublishingAgent,
    ]
    for cls in agents:
        agent = cls()
        assert hasattr(agent, "initialize")
        assert hasattr(agent, "plan")
        assert hasattr(agent, "execute")
        assert hasattr(agent, "observe")
        assert hasattr(agent, "report")
        assert hasattr(agent, "recover")


# ── LinuxAgent ────────────────────────────────────────────────────────────────


def test_linux_agent_name() -> None:
    agent = LinuxAgent()
    assert agent.name == "linux"


def test_linux_agent_initialize() -> None:
    agent = LinuxAgent()
    agent.initialize()
    assert hasattr(agent, "tools")


def test_linux_agent_plan() -> None:
    agent = LinuxAgent()
    agent.initialize()
    plan = agent.plan()
    assert isinstance(plan, list)
    assert len(plan) > 0
    assert "system-health-check" in plan


def test_linux_agent_observe() -> None:
    agent = LinuxAgent()
    agent.initialize()
    metrics = agent.observe()
    assert "cpu_percent" in metrics
    assert "memory_percent" in metrics


# ── DevOpsAgent ───────────────────────────────────────────────────────────────


def test_devops_agent_name() -> None:
    agent = DevOpsAgent()
    assert agent.name == "devops"


def test_devops_agent_plan() -> None:
    agent = DevOpsAgent()
    agent.initialize()
    plan = agent.plan()
    assert isinstance(plan, list)


# ── SecurityAgent ─────────────────────────────────────────────────────────────


def test_security_agent_name() -> None:
    agent = SecurityAgent()
    assert agent.name == "security"


def test_security_agent_plan() -> None:
    agent = SecurityAgent()
    agent.initialize()
    plan = agent.plan()
    assert "selinux-audit" in plan
    assert "firewall-audit" in plan
    assert "ports-audit" in plan


# ── AIAgent ───────────────────────────────────────────────────────────────────


def test_ai_agent_name() -> None:
    agent = AIAgent()
    assert agent.name == "ai"


def test_ai_agent_plan() -> None:
    agent = AIAgent()
    agent.initialize()
    plan = agent.plan()
    assert "ollama-ping" in plan


# ── DeveloperAgent ────────────────────────────────────────────────────────────


def test_developer_agent_name() -> None:
    agent = DeveloperAgent()
    assert agent.name == "developer"


def test_developer_agent_plan() -> None:
    agent = DeveloperAgent()
    agent.initialize()
    plan = agent.plan()
    assert isinstance(plan, list)


def test_developer_agent_observe() -> None:
    agent = DeveloperAgent()
    agent.initialize()
    metrics = agent.observe()
    assert "has_git" in metrics
    assert "dirty" in metrics


# ── MonitoringAgent ───────────────────────────────────────────────────────────


def test_monitoring_agent_name() -> None:
    agent = MonitoringAgent()
    assert agent.name == "monitoring"


def test_monitoring_agent_plan() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    plan = agent.plan()
    assert "collect-metrics" in plan
    assert "check-thresholds" in plan


def test_monitoring_agent_observe() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    metrics = agent.observe()
    assert "cpu_percent" in metrics
    assert "memory_percent" in metrics
    assert "disk_percent" in metrics


# ── DocumentationAgent ────────────────────────────────────────────────────────


def test_documentation_agent_name() -> None:
    agent = DocumentationAgent()
    assert agent.name == "documentation"


def test_documentation_agent_plan() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    plan = agent.plan()
    assert "scan-docs" in plan


# ── PublishingAgent ───────────────────────────────────────────────────────────


def test_publishing_agent_name() -> None:
    agent = PublishingAgent()
    assert agent.name == "publishing"


def test_publishing_agent_plan() -> None:
    agent = PublishingAgent()
    agent.initialize()
    plan = agent.plan()
    assert "check-version" in plan


# ── Agent reports ─────────────────────────────────────────────────────────────


def test_agent_report_format() -> None:
    """All agents produce formatted reports."""
    agents = [
        LinuxAgent(), DevOpsAgent(), SecurityAgent(), AIAgent(),
        DeveloperAgent(), MonitoringAgent(), DocumentationAgent(), PublishingAgent(),
    ]
    for agent in agents:
        agent.initialize()
        results = {"test-action": {"status": "success", "log_output": "ok", "duration_ms": 100}}
        report = agent.report(results)
        assert isinstance(report, str)
        assert "test-action" in report
