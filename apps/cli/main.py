"""Spectre CLI — Autonomous system maintenance and operations platform."""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from packages.config.settings import load_settings
from packages.core.kernel import Kernel
from packages.core.service_bus import ServiceBus
from packages.memory.db import (
    init_db,
    get_reports,
    get_workflow_runs,
    get_decisions,
    save_report,
    save_decision,
    Report,
    Decision,
)
from packages.workflow_engine.engine import WorkflowEngine

app = typer.Typer(
    name="spectre",
    help="Spectre — Autonomous system maintenance and operations platform for Fedora.",
    no_args_is_help=True,
    rich_markup_mode="rich",
)
console = Console()

# Lazy-loaded globals
_engine: WorkflowEngine | None = None
_kernel: Kernel | None = None
_service_bus: ServiceBus | None = None


def _get_engine(config: dict | None = None) -> WorkflowEngine:
    global _engine
    if _engine is None:
        settings = load_settings()
        cfg = config or {}
        cfg.setdefault("ollama_url", settings.ollama.url)
        cfg.setdefault("benchmark_model", settings.ollama.benchmark_model)
        bus = _get_service_bus()
        kernel = _get_kernel()
        _engine = WorkflowEngine(config=cfg, service_bus=bus, event_bus=kernel.event_bus)
    return _engine


def _get_kernel() -> Kernel:
    global _kernel
    if _kernel is None:
        _kernel = Kernel()
    return _kernel


def _get_service_bus() -> ServiceBus:
    global _service_bus
    if _service_bus is None:
        _service_bus = ServiceBus()
    return _service_bus


def _run_agent_action(agent_name: str, action: str) -> dict:
    engine = _get_engine()
    agent = engine.resolve_agent(agent_name)
    if not agent:
        console.print(f"[red]Unknown agent: {agent_name}[/red]")
        raise typer.Exit(1)
    results = agent.execute([action])
    return results.get(action, {})


def _print_result(action: str, result: dict) -> None:
    status = result.get("status", "unknown")
    icon = "[green]\u2713[/green]" if status == "success" else "[red]\u2717[/red]"
    msg = result.get("log_output", "No output")
    duration = result.get("duration_ms", 0)
    console.print(f"{icon} {action}: {msg} [dim]({duration}ms)[/dim]")


# ── kernel ────────────────────────────────────────────────────────────────────


@app.command()
def kernel(
    action: str = typer.Argument("status", help="Action: status, start, stop"),
) -> None:
    """Manage the Spectre Kernel lifecycle."""
    init_db()
    k = _get_kernel()

    if action == "status":
        table = Table(title="Spectre Kernel", show_header=True)
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("Running", str(k.running))
        table.add_row("Services", ", ".join(k.container.list_services()))
        console.print(table)
    elif action == "start":
        if k.running:
            console.print("[yellow]Kernel already running[/yellow]")
        else:
            k.start()
            console.print("[green]Kernel started[/green]")
    elif action == "stop":
        if not k.running:
            console.print("[yellow]Kernel not running[/yellow]")
        else:
            k.stop()
            console.print("[green]Kernel stopped[/green]")
    else:
        console.print(f"[red]Unknown action: {action}[/red]")
        raise typer.Exit(1)


# ── service-bus ───────────────────────────────────────────────────────────────


@app.command("service-bus")
def service_bus(
    list_services: bool = typer.Option(False, "--list", help="List registered services"),
    topics: bool = typer.Option(False, "--topics", help="List subscribed topics"),
) -> None:
    """Inspect the Service Bus for inter-agent communication."""
    init_db()
    bus = _get_service_bus()

    if list_services:
        table = Table(title="Service Bus — Registered Services", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Metadata")
        for svc in bus.list_services():
            meta = ", ".join(f"{k}={v}" for k, v in svc.metadata.items())
            table.add_row(svc.name, svc.service_type, meta)
        console.print(table)
    elif topics:
        table = Table(title="Service Bus — Subscribed Topics", show_header=True)
        table.add_column("Topic", style="cyan")
        table.add_column("Subscribers", style="green")
        for topic in set(list(bus._handlers.keys()) + list(bus._request_handlers.keys())):
            count = len(bus.get_subscribers(topic)) + (1 if topic in bus._request_handlers else 0)
            table.add_row(topic, str(count))
        console.print(table)
    else:
        console.print("[dim]Use --list to show services or --topics to show topics[/dim]")


# ── core ──────────────────────────────────────────────────────────────────────


@app.command()
def core() -> None:
    """Show Spectre Core status (Kernel + ServiceBus + Config)."""
    init_db()
    k = _get_kernel()
    bus = _get_service_bus()
    settings = load_settings()

    table = Table(title="Spectre Core", show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_row("Kernel", "running" if k.running else "stopped")
    table.add_row("ServiceBus", f"{len(bus.list_services())} services, {len(bus._handlers)} topics")
    table.add_row("Profile", settings.profile)
    table.add_row("Log Level", settings.log_level)
    table.add_row("Ollama", settings.ollama.url)
    table.add_row("Monitoring", f"every {settings.monitoring.interval_seconds}s")
    console.print(table)


# ── plugins ──────────────────────────────────────────────────────────────────


@app.command()
def plugins(
    list_plugins: bool = typer.Option(False, "--list", help="List loaded plugins"),
    load: str | None = typer.Option(None, "--load", help="Load plugins from directory"),
) -> None:
    """Manage Spectre plugins."""
    init_db()

    if load:
        from packages.plugins.loader import PluginLoader
        from pathlib import Path

        loader = PluginLoader(plugins_dir=Path(load))
        loaded = loader.load_plugins()
        console.print(f"[green]Loaded {len(loaded)} plugins from {load}[/green]")
        for plugin in loaded:
            console.print(f"  - {plugin.manifest.name} v{plugin.manifest.version}")
    else:
        # Show loaded plugins from memory
        from packages.memory.db import get_plugin_records
        records = get_plugin_records(limit=50)

        if list_plugins or not records:
            table = Table(title="Plugins", show_header=True)
            table.add_column("Name", style="cyan")
            table.add_column("Version", style="green")
            table.add_column("Status")
            table.add_column("Permissions")
            for rec in records:
                table.add_row(rec.name, rec.version, rec.status, rec.permissions)
            console.print(table)
        else:
            # Show from database
            table = Table(title="Plugins (from database)", show_header=True)
            table.add_column("Name", style="cyan")
            table.add_column("Version", style="green")
            table.add_column("Status")
            for rec in records:
                table.add_row(rec.name, rec.version, rec.status)
            console.print(table)


# ── doctor ────────────────────────────────────────────────────────────────────


@app.command()
def doctor() -> None:
    """Run system diagnostics and verify Kernel + ServiceBus health."""
    init_db()
    console.print(Panel("[bold]Spectre Doctor[/bold]", style="blue"))

    # Kernel status
    k = _get_kernel()
    console.print(f"[bold]Kernel:[/bold] {'running' if k.running else 'stopped'}")
    console.print(f"  Services: {', '.join(k.container.list_services())}")

    # ServiceBus status
    bus = _get_service_bus()
    services = bus.list_services()
    console.print(f"\n[bold]ServiceBus:[/bold] {len(services)} services registered")
    for svc in services:
        console.print(f"  - {svc.name} ({svc.service_type})")

    # WorkflowEngine agents
    engine = _get_engine()
    console.print(f"\n[bold]WorkflowEngine:[/bold] {len(engine.agents)} agents")
    for name in engine.agents:
        status = "ok" if engine.resolve_agent(name) else "missing"
        console.print(f"  - {name}: {status}")

    # System health
    console.print("\n[bold]System Health:[/bold]")
    result = _run_agent_action("linux", "system-health-check")
    _print_result("system-health-check", result)

    # Container status
    result = _run_agent_action("devops", "podman-status")
    _print_result("podman-status", result)

    # AI status
    result = _run_agent_action("ai", "ollama-ping")
    _print_result("ollama-ping", result)

    # Developer tools
    result = _run_agent_action("developer", "git-status")
    _print_result("git-status", result)

    console.print("\n[bold green]Doctor check complete.[/bold green]")


# ── health ────────────────────────────────────────────────────────────────────


@app.command()
def health() -> None:
    """Display system health metrics."""
    init_db()
    result = _run_agent_action("monitoring", "collect-metrics")
    _print_result("collect-metrics", result)

    result = _run_agent_action("monitoring", "check-thresholds")
    _print_result("check-thresholds", result)


# ── status ────────────────────────────────────────────────────────────────────


@app.command()
def status() -> None:
    """Show overall system status."""
    init_db()
    engine = _get_engine()

    table = Table(title="Spectre Status", show_header=True)
    table.add_column("Component", style="cyan")
    table.add_column("Status", style="green")
    table.add_column("Details")

    # Linux
    result = _run_agent_action("linux", "system-health-check")
    table.add_row("Linux", result.get("status", "?"), result.get("log_output", ""))

    # DevOps
    result = _run_agent_action("devops", "podman-status")
    table.add_row("Podman", result.get("status", "?"), result.get("log_output", ""))

    result = _run_agent_action("devops", "docker-status")
    table.add_row("Docker", result.get("status", "?"), result.get("log_output", ""))

    # Security
    result = _run_agent_action("security", "selinux-audit")
    table.add_row("SELinux", result.get("status", "?"), result.get("log_output", ""))

    result = _run_agent_action("security", "firewall-audit")
    table.add_row("Firewall", result.get("status", "?"), result.get("log_output", ""))

    # AI
    result = _run_agent_action("ai", "ollama-ping")
    table.add_row("Ollama", result.get("status", "?"), result.get("log_output", ""))

    console.print(table)


# ── monitor ───────────────────────────────────────────────────────────────────


@app.command()
def monitor(interval: int = typer.Option(0, help="If >0, monitor continuously")) -> None:
    """Display live system metrics."""
    init_db()

    if interval > 0:
        console.print(f"[dim]Monitoring every {interval}s (Ctrl+C to stop)[/dim]")
        try:
            while True:
                result = _run_agent_action("monitoring", "collect-metrics")
                console.print(f"[{time.strftime('%H:%M:%S')}] {result.get('log_output', '')}")
                time.sleep(interval)
        except KeyboardInterrupt:
            console.print("\n[dim]Monitoring stopped.[/dim]")
    else:
        result = _run_agent_action("monitoring", "collect-metrics")
        _print_result("collect-metrics", result)


# ── update ────────────────────────────────────────────────────────────────────


@app.command()
def update() -> None:
    """Check for system updates."""
    init_db()
    result = _run_agent_action("linux", "dnf-check-update")
    _print_result("dnf-check-update", result)


# ── clean ─────────────────────────────────────────────────────────────────────


@app.command()
def clean() -> None:
    """Clean system caches and unused packages."""
    init_db()
    engine = _get_engine()

    console.print("[bold]Cleaning Flatpak...[/bold]")
    result = _run_agent_action("linux", "flatpak-prune")
    _print_result("flatpak-prune", result)

    console.print("[bold]Cleaning journals...[/bold]")
    result = _run_agent_action("linux", "journal-cleanup")
    _print_result("journal-cleanup", result)

    console.print("[bold]Cleaning containers...[/bold]")
    result = _run_agent_action("devops", "podman-prune")
    _print_result("podman-prune", result)

    result = _run_agent_action("devops", "docker-prune")
    _print_result("docker-prune", result)


# ── repair ────────────────────────────────────────────────────────────────────


@app.command()
def repair() -> None:
    """Attempt system repair and health restoration."""
    init_db()
    engine = _get_engine()

    console.print("[bold]Running system health check...[/bold]")
    result = _run_agent_action("linux", "system-health-check")
    _print_result("system-health-check", result)

    console.print("[bold]Checking failed services...[/bold]")
    result = _run_agent_action("linux", "system-health-check")
    _print_result("system-health-check", result)


# ── optimize ──────────────────────────────────────────────────────────────────


@app.command()
def optimize() -> None:
    """Run system optimization workflows."""
    init_db()
    engine = _get_engine()
    console.print(Panel("[bold]Running monthly optimization workflow[/bold]", style="blue"))
    result = engine.run_workflow("monthly-optimization")
    status = result.get("status", "unknown")
    console.print(f"\n[bold]Workflow completed: {status}[/bold]")


# ── security ──────────────────────────────────────────────────────────────────


@app.command()
def security(audit: bool = typer.Option(False, "--audit", help="Run full security audit")) -> None:
    """Security status and auditing."""
    init_db()

    if audit:
        console.print(Panel("[bold]Running full security audit[/bold]", style="red"))
        actions = ["selinux-audit", "firewall-audit", "ports-audit", "secrets-scan", "ssh-audit"]
        for action in actions:
            result = _run_agent_action("security", action)
            _print_result(action, result)
    else:
        result = _run_agent_action("security", "selinux-audit")
        _print_result("selinux-audit", result)

        result = _run_agent_action("security", "firewall-audit")
        _print_result("firewall-audit", result)

        result = _run_agent_action("security", "ports-audit")
        _print_result("ports-audit", result)


# ── services ──────────────────────────────────────────────────────────────────


@app.command()
def services() -> None:
    """Manage systemd services."""
    init_db()
    result = _run_agent_action("linux", "system-health-check")
    _print_result("system-health-check", result)


# ── containers ────────────────────────────────────────────────────────────────


@app.command()
def containers(
    prune: bool = typer.Option(False, "--prune", help="Prune unused containers"),
) -> None:
    """List and manage containers."""
    init_db()

    if prune:
        console.print("[bold]Pruning containers...[/bold]")
        result = _run_agent_action("devops", "podman-prune")
        _print_result("podman-prune", result)
        result = _run_agent_action("devops", "docker-prune")
        _print_result("docker-prune", result)
    else:
        result = _run_agent_action("devops", "podman-status")
        _print_result("podman-status", result)
        result = _run_agent_action("devops", "docker-status")
        _print_result("docker-status", result)


# ── models ────────────────────────────────────────────────────────────────────


@app.command()
def models(
    list_models: bool = typer.Option(False, "--list", help="List installed models"),
    benchmark: bool = typer.Option(False, "--benchmark", help="Benchmark first model"),
) -> None:
    """Manage AI models (Ollama)."""
    init_db()

    if list_models:
        result = _run_agent_action("ai", "list-models")
        _print_result("list-models", result)
    elif benchmark:
        result = _run_agent_action("ai", "benchmark-model")
        _print_result("benchmark-model", result)
    else:
        result = _run_agent_action("ai", "ollama-ping")
        _print_result("ollama-ping", result)


# ── workflows ─────────────────────────────────────────────────────────────────


@app.command()
def workflows(
    name: Optional[str] = typer.Argument(None, help="Workflow name to run"),
    list_workflows: bool = typer.Option(False, "--list", help="List available workflows"),
    load_dir: Optional[str] = typer.Option(None, "--load", help="Load custom workflows from directory"),
    definitions: bool = typer.Option(False, "--definitions", help="Show workflow definitions"),
) -> None:
    """Execute or list maintenance workflows."""
    init_db()
    engine = _get_engine()

    if load_dir:
        from pathlib import Path
        count = engine.load_workflows(Path(load_dir))
        console.print(f"[green]Loaded {count} custom workflows from {load_dir}[/green]")
        return

    if list_workflows or name is None:
        table = Table(title="Available Workflows", show_header=True)
        table.add_column("Workflow", style="cyan")
        table.add_column("Description")
        table.add_column("Type", style="green")
        descriptions = {
            "morning-startup": "Daily morning health check and AI ping",
            "weekly-maintenance": "Full weekly maintenance cycle",
            "security-audit": "Complete security audit scan",
            "container-cleanup": "Prune container environments",
            "model-cleanup": "Verify Ollama and benchmark models",
            "shutdown": "Pre-shutdown system checks",
            "monthly-optimization": "Comprehensive monthly optimization",
            "dependency-updates": "Check for outdated dependencies",
            "backup": "Backup verification",
            "restore": "Post-restore verification",
        }
        all_defs = engine.get_workflow_definitions()
        for wf in engine.get_available_workflows():
            wf_type = "custom" if wf in engine.custom_workflows else "built-in"
            table.add_row(wf, descriptions.get(wf, all_defs.get(wf, {}).description if hasattr(all_defs.get(wf, {}), 'description') else ""), wf_type)
        console.print(table)
        return

    if definitions:
        all_defs = engine.get_workflow_definitions()
        if name not in all_defs:
            console.print(f"[red]Workflow '{name}' not found[/red]")
            raise typer.Exit(1)
        wf = all_defs[name]
        console.print(Panel(f"[bold]{wf.name}[/bold]\n{wf.description}", title="Workflow Definition"))
        table = Table(show_header=True)
        table.add_column("Step", style="cyan")
        table.add_column("Agent", style="green")
        table.add_column("Action")
        table.add_column("Retries")
        for i, step in enumerate(wf.steps, 1):
            table.add_row(str(i), step.agent, step.action, str(step.max_retries))
        console.print(table)
        return

    console.print(Panel(f"[bold]Running workflow: {name}[/bold]", style="blue"))
    try:
        result = engine.run_workflow(name)
        status = result.get("status", "unknown")
        duration = result.get("duration_ms", 0)
        console.print(f"\n[bold]Workflow '{name}' completed: {status} ({duration}ms)[/bold]")
    except ValueError as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


# ── backup ────────────────────────────────────────────────────────────────────


@app.command()
def backup() -> None:
    """Backup configuration and data."""
    init_db()
    engine = _get_engine()
    console.print(Panel("[bold]Running backup workflow[/bold]", style="green"))
    result = engine.run_workflow("backup")
    status = result.get("status", "unknown")
    console.print(f"\n[bold]Backup completed: {status}[/bold]")


# ── restore ───────────────────────────────────────────────────────────────────


@app.command()
def restore() -> None:
    """Restore configuration and data."""
    init_db()
    engine = _get_engine()
    console.print(Panel("[bold]Running restore verification[/bold]", style="green"))
    result = engine.run_workflow("restore")
    status = result.get("status", "unknown")
    console.print(f"\n[bold]Restore verification completed: {status}[/bold]")


# ── report ────────────────────────────────────────────────────────────────────


@app.command()
def report(
    report_type: str = typer.Option("daily", help="Report type: daily, weekly, security, maintenance"),
    output: Optional[str] = typer.Option(None, help="Output file path"),
) -> None:
    """Generate system reports."""
    init_db()
    engine = _get_engine()

    console.print(f"[bold]Generating {report_type} report...[/bold]")

    # Collect data from agents
    sections: list[str] = []
    sections.append(f"# Spectre {report_type.title()} Report\n")

    # System health
    result = _run_agent_action("monitoring", "collect-metrics")
    sections.append(f"## System Metrics\n{result.get('log_output', 'N/A')}\n")

    # Security
    result = _run_agent_action("security", "selinux-audit")
    sections.append(f"## SELinux\n{result.get('log_output', 'N/A')}\n")

    result = _run_agent_action("security", "firewall-audit")
    sections.append(f"## Firewall\n{result.get('log_output', 'N/A')}\n")

    # Containers
    result = _run_agent_action("devops", "podman-status")
    sections.append(f"## Podman\n{result.get('log_output', 'N/A')}\n")

    # Developer
    result = _run_agent_action("developer", "git-status")
    sections.append(f"## Git Status\n{result.get('log_output', 'N/A')}\n")

    content = "\n".join(sections)

    # Save to database
    save_report(Report(report_type=report_type, content=content, format="markdown"))

    if output:
        Path(output).write_text(content, encoding="utf-8")
        console.print(f"[green]Report saved to {output}[/green]")
    else:
        console.print(Panel(content, title=f"{report_type.title()} Report"))


# ── config ────────────────────────────────────────────────────────────────────


@app.command()
def config(
    get_key: Optional[str] = typer.Option(None, "--get", help="Get a configuration value"),
    set_key: Optional[str] = typer.Option(None, "--set", help="Set a configuration key"),
    set_value: Optional[str] = typer.Option(None, "--value", help="Value to set (used with --set)"),
    show: bool = typer.Option(False, "--show", help="Show current configuration"),
) -> None:
    """Manage Spectre configuration."""
    init_db()
    settings = load_settings()

    if show:
        table = Table(title="Spectre Configuration", show_header=True)
        table.add_column("Key", style="cyan")
        table.add_column("Value", style="green")
        table.add_row("profile", settings.profile)
        table.add_row("log_level", settings.log_level)
        table.add_row("ollama_url", settings.ollama.url)
        table.add_row("ollama_benchmark_model", settings.ollama.benchmark_model)
        table.add_row("monitoring_interval", str(settings.monitoring.interval_seconds))
        table.add_row("monitoring_enabled", str(settings.monitoring.enabled))
        console.print(table)
        return

    if get_key:
        from packages.memory.db import get_configuration
        value = get_configuration(get_key, profile=settings.profile)
        if value is None:
            console.print(f"[yellow]Key '{get_key}' not found[/yellow]")
        else:
            console.print(f"{get_key} = {value}")
        return

    if set_key and set_value:
        from packages.memory.db import save_configuration, Configuration
        save_configuration(Configuration(key=set_key, value=set_value, profile=settings.profile))
        console.print(f"[green]Set {set_key} = {set_value}[/green]")
        return

    console.print("[dim]Use --show to display config, --get <key> to read, or --set <key> --value <val> to write[/dim]")


# ── events ────────────────────────────────────────────────────────────────────


@app.command()
def events(
    event_type: Optional[str] = typer.Option(None, "--type", help="Filter by event type"),
    limit: int = typer.Option(20, "--limit", help="Number of events to show"),
) -> None:
    """View recent system events from the EventBus."""
    init_db()
    from packages.memory.db import get_events

    records = get_events(event_type=event_type, limit=limit)

    if not records:
        console.print("[dim]No events recorded yet[/dim]")
        return

    table = Table(title="System Events", show_header=True)
    table.add_column("Time", style="cyan")
    table.add_column("Type", style="green")
    table.add_column("Source")
    table.add_column("Severity")
    table.add_column("Data")

    for event in records:
        data_preview = event.data_json[:80] + "..." if len(event.data_json) > 80 else event.data_json
        table.add_row(
            event.timestamp.strftime("%H:%M:%S"),
            event.event_type,
            event.source,
            event.severity,
            data_preview,
        )
    console.print(table)


# ── version ────────────────────────────────────────────────────────────────────


@app.command()
def version() -> None:
    """Show Spectre version and system information."""
    from importlib.metadata import version as get_version, PackageNotFoundError

    try:
        spectre_version = get_version("spectre")
    except PackageNotFoundError:
        spectre_version = "0.2.0-dev"

    import platform
    import psutil

    table = Table(title="Spectre Version Info", show_header=False)
    table.add_column("Key", style="cyan")
    table.add_column("Value", style="green")
    table.add_row("spectre", spectre_version)
    table.add_row("python", platform.python_version())
    table.add_row("platform", f"{platform.system()} {platform.release()}")
    table.add_row("machine", platform.machine())
    table.add_row("cpu_count", str(psutil.cpu_count()))
    table.add_row("ram", f"{psutil.virtual_memory().total / (1024**3):.1f} GB")
    console.print(table)


# ── daemon ─────────────────────────────────────────────────────────────────────


@app.command()
def daemon(
    action: str = typer.Argument("status", help="Action: status, start, stop"),
) -> None:
    """Manage the Spectre background daemon."""
    import subprocess
    import os

    service_name = "spectre"

    if action == "status":
        result = subprocess.run(
            ["systemctl", "--user", "is-active", service_name],
            capture_output=True, text=True,
        )
        status = result.stdout.strip()
        if status == "active":
            console.print(f"[green]{service_name} is running[/green]")
        elif status == "inactive":
            console.print(f"[yellow]{service_name} is stopped[/yellow]")
        else:
            console.print(f"[dim]{service_name} status: {status or 'unknown'}[/dim]")

    elif action == "start":
        result = subprocess.run(
            ["systemctl", "--user", "start", service_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print(f"[green]{service_name} started[/green]")
        else:
            console.print(f"[red]Failed to start {service_name}: {result.stderr}[/red]")
            raise typer.Exit(1)

    elif action == "stop":
        result = subprocess.run(
            ["systemctl", "--user", "stop", service_name],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            console.print(f"[green]{service_name} stopped[/green]")
        else:
            console.print(f"[red]Failed to stop {service_name}: {result.stderr}[/red]")
            raise typer.Exit(1)

    else:
        console.print(f"[red]Unknown action: {action}. Use status, start, or stop[/red]")
        raise typer.Exit(1)


# ── init ───────────────────────────────────────────────────────────────────────


@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite existing config"),
) -> None:
    """Initialize Spectre configuration and directories."""
    from packages.config.settings import DEFAULT_CONFIG_PATH, save_settings, SpectreSettings

    # Create directories
    dirs = [
        DEFAULT_CONFIG_PATH.parent,
        Path.home() / ".config" / "spectre" / "workflows",
        Path.home() / ".config" / "spectre" / "plugins",
    ]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        console.print(f"[dim]Created {d}[/dim]")

    # Initialize database
    init_db()
    console.print("[dim]Initialized database[/dim]")

    # Create default settings if not exists
    if not DEFAULT_CONFIG_PATH.exists() or force:
        settings = SpectreSettings()
        save_settings(settings, DEFAULT_CONFIG_PATH)
        console.print(f"[green]Created default config at {DEFAULT_CONFIG_PATH}[/green]")
    else:
        console.print(f"[yellow]Config already exists at {DEFAULT_CONFIG_PATH}[/yellow]")

    # Create sample workflow
    sample_workflow = Path.home() / ".config" / "spectre" / "workflows" / "sample.yaml"
    if not sample_workflow.exists() or force:
        import yaml
        sample = {
            "name": "sample-workflow",
            "description": "A sample custom workflow",
            "steps": [
                {"agent": "linux", "action": "system-health-check"},
                {"agent": "monitoring", "action": "collect-metrics"},
            ],
        }
        sample_workflow.write_text(yaml.safe_dump(sample, default_flow_style=False))
        console.print(f"[green]Created sample workflow at {sample_workflow}[/green]")

    console.print("\n[bold green]Spectre initialized successfully![/bold green]")
    console.print("\n[yellow]Next steps:[/yellow]")
    console.print("  1. spectre doctor       - Check system health")
    console.print("  2. spectre daemon start - Start the background daemon")
    console.print("  3. spectre workflows    - List available workflows")


# ── logs ──────────────────────────────────────────────────────────────────────


@app.command()
def logs(
    lines: int = typer.Option(50, "--lines", "-n", help="Number of lines to show"),
    follow: bool = typer.Option(False, "--follow", "-f", help="Follow log output"),
    service: str = typer.Option("spectre", "--service", "-s", help="Service name"),
) -> None:
    """View Spectre daemon logs."""
    import subprocess

    cmd = ["journalctl", "--user", "-u", service, "--no-pager", "-n", str(lines)]
    if follow:
        cmd.append("-f")

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=5 if not follow else None)
        if result.returncode == 0:
            console.print(result.stdout)
        else:
            console.print(f"[yellow]No logs available for {service}[/yellow]")
    except subprocess.TimeoutExpired:
        pass
    except KeyboardInterrupt:
        pass


# ── export ────────────────────────────────────────────────────────────────────


@app.command()
def export(
    output: str = typer.Option("spectre-export.json", "--output", "-o", help="Output file"),
    data_type: str = typer.Option("all", "--type", "-t", help="Data type: all, events, reports, workflows, config"),
    limit: int = typer.Option(100, "--limit", help="Max records per type"),
) -> None:
    """Export Spectre data to JSON."""
    import json

    init_db()
    from packages.memory.db import get_events, get_reports, get_workflow_runs, get_configuration

    export_data: dict[str, Any] = {"version": "0.2.0", "exported_at": __import__("datetime").datetime.now().isoformat()}

    if data_type in ("all", "events"):
        events = get_events(limit=limit)
        export_data["events"] = [
            {
                "timestamp": e.timestamp.isoformat(),
                "event_type": e.event_type,
                "source": e.source,
                "severity": e.severity,
                "data": json.loads(e.data_json) if e.data_json else {},
            }
            for e in events
        ]

    if data_type in ("all", "reports"):
        reports = get_reports(limit=limit)
        export_data["reports"] = [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "type": r.report_type,
                "content": r.content,
            }
            for r in reports
        ]

    if data_type in ("all", "workflows"):
        runs = get_workflow_runs(limit=limit)
        export_data["workflows"] = [
            {
                "id": r.id,
                "timestamp": r.timestamp.isoformat(),
                "workflow": r.workflow,
                "status": r.status,
                "duration_ms": r.duration_ms,
            }
            for r in runs
        ]

    if data_type in ("all", "config"):
        from packages.memory.db import engine as db_engine, Configuration
        from sqlmodel import select, Session

        with Session(db_engine) as session:
            configs = list(session.exec(select(Configuration).limit(limit)))
        export_data["config"] = [{"key": c.key, "value": c.value, "profile": c.profile} for c in configs]

    Path(output).write_text(json.dumps(export_data, indent=2))
    console.print(f"[green]Exported data to {output}[/green]")
    console.print(f"[dim]Events: {len(export_data.get('events', []))}, Reports: {len(export_data.get('reports', []))}, Workflows: {len(export_data.get('workflows', []))}, Config: {len(export_data.get('config', []))}[/dim]")


# ── main ──────────────────────────────────────────────────────────────────────


def main(args: list[str] | None = None) -> int:
    """Entry point for the Spectre CLI."""
    try:
        app(args=args or sys.argv[1:])
        return 0
    except typer.Exit as e:
        return e.exit_code
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return 1


if __name__ == "__main__":
    main()
