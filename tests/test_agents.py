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
    assert "check-links" in plan
    assert "coverage-report" in plan


def test_documentation_agent_execute() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    results = agent.execute(["scan-docs"])
    assert "scan-docs" in results
    assert results["scan-docs"]["status"] in ("success", "failed")


def test_documentation_agent_observe() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    metrics = agent.observe()
    assert "docs_dir_exists" in metrics
    assert "markdown_files" in metrics
    assert "python_files" in metrics
    assert "documented_modules" in metrics
    assert isinstance(metrics["markdown_files"], int)
    assert isinstance(metrics["python_files"], int)


def test_documentation_agent_verify() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    assert agent.verify() is True


def test_documentation_agent_recover() -> None:
    agent = DocumentationAgent()
    assert agent.recover(Exception("test")) is True


def test_documentation_agent_shutdown() -> None:
    agent = DocumentationAgent()
    agent.shutdown()  # Should not raise


def test_documentation_agent_scan_docs() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    output = agent._scan_docs()
    assert "markdown files" in output.lower()


def test_documentation_agent_check_links() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    output = agent._check_links()
    assert isinstance(output, str)


def test_documentation_agent_coverage_report() -> None:
    agent = DocumentationAgent()
    agent.initialize()
    output = agent._coverage_report()
    assert "coverage" in output.lower() or "docstring" in output.lower()


# ── PublishingAgent ───────────────────────────────────────────────────────────


def test_publishing_agent_name() -> None:
    agent = PublishingAgent()
    assert agent.name == "publishing"


def test_publishing_agent_plan() -> None:
    agent = PublishingAgent()
    agent.initialize()
    plan = agent.plan()
    assert "check-version" in plan
    assert "validate-dist" in plan
    assert "check-git-status" in plan


def test_publishing_agent_execute() -> None:
    agent = PublishingAgent()
    agent.initialize()
    results = agent.execute(["check-version"])
    assert "check-version" in results
    assert results["check-version"]["status"] in ("success", "failed")


def test_publishing_agent_observe() -> None:
    agent = PublishingAgent()
    agent.initialize()
    metrics = agent.observe()
    assert "version" in metrics
    assert "git_tag" in metrics
    assert "dirty" in metrics
    assert "registry" in metrics
    assert "package_name" in metrics


def test_publishing_agent_verify() -> None:
    agent = PublishingAgent()
    agent.initialize()
    # verify returns bool
    result = agent.verify()
    assert isinstance(result, bool)


def test_publishing_agent_recover() -> None:
    agent = PublishingAgent()
    assert agent.recover(Exception("test")) is True


def test_publishing_agent_shutdown() -> None:
    agent = PublishingAgent()
    agent.shutdown()  # Should not raise


def test_publishing_agent_check_version() -> None:
    agent = PublishingAgent()
    agent.initialize()
    output = agent._check_version()
    assert "version" in output.lower() or "could not determine" in output.lower()


def test_publishing_agent_validate_dist() -> None:
    agent = PublishingAgent()
    agent.initialize()
    output = agent._validate_dist()
    assert isinstance(output, str)


def test_publishing_agent_check_git_status() -> None:
    agent = PublishingAgent()
    agent.initialize()
    output = agent._check_git_status()
    assert "working tree" in output.lower() or "git check failed" in output.lower()


def test_publishing_agent_get_version_from_pyproject() -> None:
    agent = PublishingAgent()
    version = agent._get_version_from_pyproject()
    assert version is not None
    assert isinstance(version, str)


def test_publishing_agent_get_latest_git_tag() -> None:
    agent = PublishingAgent()
    tag = agent._get_latest_git_tag()
    # May be None if no tags
    assert tag is None or isinstance(tag, str)


def test_publishing_agent_is_dirty() -> None:
    agent = PublishingAgent()
    dirty = agent._is_dirty()
    assert isinstance(dirty, bool)


# ── MonitoringAgent ───────────────────────────────────────────────────────────


def test_monitoring_agent_execute() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    results = agent.execute(["collect-metrics"])
    assert "collect-metrics" in results
    assert results["collect-metrics"]["status"] in ("success", "failed")


def test_monitoring_agent_verify() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    assert agent.verify() is True


def test_monitoring_agent_recover() -> None:
    agent = MonitoringAgent()
    assert agent.recover(Exception("test")) is True


def test_monitoring_agent_shutdown() -> None:
    agent = MonitoringAgent()
    agent.shutdown()  # Should not raise


def test_monitoring_agent_gather_metrics() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    metrics = agent._gather_metrics()
    assert "cpu_percent" in metrics
    assert "memory_percent" in metrics
    assert isinstance(metrics["cpu_percent"], float)
    assert isinstance(metrics["memory_percent"], float)


def test_monitoring_agent_collect_metrics() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    output = agent._collect_metrics()
    assert "CPU:" in output
    assert "RAM:" in output
    assert "Disk:" in output


def test_monitoring_agent_check_thresholds() -> None:
    agent = MonitoringAgent()
    agent.initialize()
    output = agent._check_thresholds()
    assert isinstance(output, str)
    assert "ALERTS:" in output or "All metrics within thresholds" in output or "System healthy" in output


def test_monitoring_agent_threshold_config() -> None:
    agent = MonitoringAgent(config={"cpu_threshold": 50, "memory_threshold": 60})
    agent.initialize()
    assert agent.thresholds["cpu_percent"] == 50
    assert agent.thresholds["memory_percent"] == 60


# ── LinuxAgent ────────────────────────────────────────────────────────────────


def test_linux_agent_execute() -> None:
    agent = LinuxAgent()
    agent.initialize()
    results = agent.execute(["system-health-check"])
    assert "system-health-check" in results


def test_linux_agent_verify() -> None:
    agent = LinuxAgent()
    agent.initialize()
    assert agent.verify() is True


def test_linux_agent_recover() -> None:
    agent = LinuxAgent()
    assert agent.recover(Exception("test")) is True


def test_linux_agent_shutdown() -> None:
    agent = LinuxAgent()
    agent.shutdown()


def test_linux_agent_run_system_health() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_system_health()
    assert isinstance(output, str)


def test_linux_agent_run_dnf_check() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_dnf_check()
    assert isinstance(output, str)


def test_linux_agent_run_flatpak_prune() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_flatpak_prune()
    assert isinstance(output, str)


def test_linux_agent_run_journal_cleanup() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_journal_cleanup()
    assert isinstance(output, str)


def test_linux_agent_run_selinux_check() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_selinux_check()
    assert "SELinux" in output


def test_linux_agent_run_firewall_check() -> None:
    agent = LinuxAgent()
    agent.initialize()
    output = agent._run_firewall_check()
    assert "Firewalld" in output


# ── DevOpsAgent ───────────────────────────────────────────────────────────────


def test_devops_agent_execute() -> None:
    agent = DevOpsAgent()
    agent.initialize()
    results = agent.execute(["podman-status"])
    assert "podman-status" in results


def test_devops_agent_verify() -> None:
    agent = DevOpsAgent()
    agent.initialize()
    assert agent.verify() is True


def test_devops_agent_recover() -> None:
    agent = DevOpsAgent()
    assert agent.recover(Exception("test")) is True


def test_devops_agent_shutdown() -> None:
    agent = DevOpsAgent()
    agent.shutdown()


# ── SecurityAgent ─────────────────────────────────────────────────────────────


def test_security_agent_execute() -> None:
    agent = SecurityAgent()
    agent.initialize()
    results = agent.execute(["selinux-audit"])
    assert "selinux-audit" in results


def test_security_agent_verify() -> None:
    agent = SecurityAgent()
    agent.initialize()
    assert agent.verify() is True


def test_security_agent_recover() -> None:
    agent = SecurityAgent()
    assert agent.recover(Exception("test")) is True


def test_security_agent_shutdown() -> None:
    agent = SecurityAgent()
    agent.shutdown()


def test_security_agent_audit_selinux() -> None:
    agent = SecurityAgent()
    agent.initialize()
    output = agent._audit_selinux()
    assert "SELinux" in output


def test_security_agent_audit_firewall() -> None:
    agent = SecurityAgent()
    agent.initialize()
    output = agent._audit_firewall()
    assert "Firewalld" in output


def test_security_agent_audit_ports() -> None:
    agent = SecurityAgent()
    agent.initialize()
    output = agent._audit_ports()
    assert isinstance(output, str)


def test_security_agent_scan_secrets() -> None:
    agent = SecurityAgent()
    agent.initialize()
    output = agent._scan_secrets()
    assert isinstance(output, str)


def test_security_agent_audit_ssh() -> None:
    agent = SecurityAgent()
    agent.initialize()
    output = agent._audit_ssh()
    assert isinstance(output, str)


# ── AIAgent ───────────────────────────────────────────────────────────────────


def test_ai_agent_execute() -> None:
    agent = AIAgent()
    agent.initialize()
    results = agent.execute(["ollama-ping"])
    assert "ollama-ping" in results


def test_ai_agent_verify() -> None:
    agent = AIAgent()
    agent.initialize()
    # verify returns True if Ollama is available, False otherwise
    assert isinstance(agent.verify(), bool)


def test_ai_agent_recover() -> None:
    agent = AIAgent()
    assert agent.recover(Exception("test")) is True


def test_ai_agent_shutdown() -> None:
    agent = AIAgent()
    agent.shutdown()


# ── DeveloperAgent ────────────────────────────────────────────────────────────


def test_developer_agent_execute() -> None:
    agent = DeveloperAgent()
    agent.initialize()
    results = agent.execute(["git-status"])
    assert "git-status" in results


def test_developer_agent_verify() -> None:
    agent = DeveloperAgent()
    agent.initialize()
    assert agent.verify() is True


def test_developer_agent_recover() -> None:
    agent = DeveloperAgent()
    assert agent.recover(Exception("test")) is True


def test_developer_agent_shutdown() -> None:
    agent = DeveloperAgent()
    agent.shutdown()
