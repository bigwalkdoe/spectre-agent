"""Spectre CLI — Autonomous system maintenance and operations platform."""

from __future__ import annotations

import sys
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from packages.config.settings import load_settings
from packages.core.kernel import Kernel
from packages.core.service_bus import ServiceBus
from packages.memory.db import (
    Report,
    init_db,
    save_report,
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
    install: str | None = typer.Option(None, "--install", help="Install plugin from directory"),
    search: str | None = typer.Option(None, "--search", help="Search for plugins"),
    remove: str | None = typer.Option(None, "--remove", help="Remove plugin by name"),
) -> None:
    """Manage Spectre plugins."""
    init_db()

    if remove:
        from sqlmodel import Session, select

        from packages.memory.db import PluginRecord
        from packages.memory.db import engine as db_engine

        with Session(db_engine) as session:
            plugin = session.exec(
                select(PluginRecord).where(PluginRecord.name == remove)
            ).first()
            if not plugin:
                console.print(f"[yellow]Plugin '{remove}' not found[/yellow]")
                return
            session.delete(plugin)
            session.commit()
            console.print(f"[green]Removed plugin '{remove}'[/green]")

    if search:
        # Search for plugins in common locations
        from pathlib import Path

        import yaml

        search_paths = [
            Path.home() / ".config" / "spectre" / "plugins",
            Path("/usr/share/spectre/plugins"),
            Path("/opt/spectre/plugins"),
        ]

        found = []
        for search_path in search_paths:
            if not search_path.is_dir():
                continue
            for plugin_dir in search_path.iterdir():
                if not plugin_dir.is_dir():
                    continue
                manifest = plugin_dir / "manifest.yaml"
                if manifest.exists():
                    try:
                        with open(manifest) as f:
                            data = yaml.safe_load(f)
                        if (
                            search.lower() in data.get("name", "").lower()
                            or search.lower() in data.get("description", "").lower()
                        ):
                            found.append({
                                "name": data.get("name", plugin_dir.name),
                                "version": data.get("version", "unknown"),
                                "description": data.get("description", ""),
                                "path": str(plugin_dir),
                            })
                    except Exception:
                        pass

        if found:
            table = Table(title=f"Plugins matching '{search}'", show_header=True)
            table.add_column("Name", style="cyan")
            table.add_column("Version", style="green")
            table.add_column("Description")
            table.add_column("Path", style="dim")
            for found_plugin in found:
                table.add_row(
                    found_plugin["name"], found_plugin["version"],
                    found_plugin["description"][:50], found_plugin["path"],
                )
            console.print(table)
        else:
            console.print(f"[dim]No plugins found matching '{search}'[/dim]")
            console.print("[dim]Searched in: ~/.config/spectre/plugins, /usr/share/spectre/plugins, /opt/spectre/plugins[/dim]")  # noqa: E501

    elif install:
        from pathlib import Path

        from packages.memory.db import PluginRecord, save_plugin_record
        from packages.plugins.loader import PluginLoader

        plugin_dir = Path(install)
        if not plugin_dir.is_dir():
            console.print(f"[red]Directory not found: {install}[/red]")
            raise typer.Exit(1)

        # Check for manifest
        manifest_file = plugin_dir / "manifest.yaml"
        if not manifest_file.exists():
            manifest_file = plugin_dir / "manifest.json"
        if not manifest_file.exists():
            console.print(f"[red]No manifest.yaml or manifest.json found in {install}[/red]")
            raise typer.Exit(1)

        # Load the plugin
        loader = PluginLoader(plugins_dir=plugin_dir.parent)
        loaded = loader.load_plugins()
        if loaded:
            loaded_plugin = loaded[0]
            save_plugin_record(PluginRecord(
                name=loaded_plugin.manifest.name,
                version=loaded_plugin.manifest.version,
                status="installed",
                permissions=",".join(loaded_plugin.manifest.permissions),
            ))
            console.print(f"[green]Installed plugin: {loaded_plugin.manifest.name} v{loaded_plugin.manifest.version}[/green]")  # noqa: E501
        else:
            console.print("[red]Failed to load plugin[/red]")
            raise typer.Exit(1)

    elif load:
        from pathlib import Path

        from packages.plugins.loader import PluginLoader

        loader = PluginLoader(plugins_dir=Path(load))
        loaded = loader.load_plugins()
        console.print(f"[green]Loaded {len(loaded)} plugins from {load}[/green]")
        for loaded_plugin in loaded:
            console.print(f"  - {loaded_plugin.manifest.name} v{loaded_plugin.manifest.version}")
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
def doctor(
    fix: bool = typer.Option(False, "--fix", help="Auto-fix issues"),
) -> None:
    """Run system diagnostics and verify Kernel + ServiceBus health."""
    init_db()
    console.print(Panel("[bold]Spectre Doctor[/bold]", style="blue"))

    issues = []

    # Kernel status
    k = _get_kernel()
    kernel_status = "running" if k.running else "stopped"
    console.print(f"[bold]Kernel:[/bold] {kernel_status}")
    console.print(f"  Services: {', '.join(k.container.list_services())}")

    if not k.running and fix:
        console.print("[dim]Starting kernel...[/dim]")
        k.start()
        console.print("[green]Kernel started[/green]")

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
        agent = engine.resolve_agent(name)
        status = "ok" if agent else "missing"
        console.print(f"  - {name}: {status}")
        if not agent:
            issues.append(f"Agent '{name}' not registered with ServiceBus")

    # System health
    console.print("\n[bold]System Health:[/bold]")
    result = _run_agent_action("linux", "system-health-check")
    _print_result("system-health-check", result)
    if result.get("status") == "failed":
        issues.append("System health check failed")

    # Container status
    result = _run_agent_action("devops", "podman-status")
    _print_result("podman-status", result)

    # AI status
    result = _run_agent_action("ai", "ollama-ping")
    _print_result("ollama-ping", result)

    # Developer tools
    result = _run_agent_action("developer", "git-status")
    _print_result("git-status", result)

    # Summary
    if issues:
        console.print(f"\n[bold yellow]Found {len(issues)} issue(s):[/bold yellow]")
        for issue in issues:
            console.print(f"  [yellow]![/yellow] {issue}")

        if fix:
            console.print("\n[bold]Attempting fixes...[/bold]")
            fixed = 0

            # Try to re-register missing agents
            for name in engine.agents:
                if not engine.resolve_agent(name):
                    agent = engine.agents[name]
                    if hasattr(agent, 'initialize'):
                        try:
                            agent.initialize()
                            fixed += 1
                            console.print(f"  [green]✓ Re-registered {name}[/green]")
                        except Exception as e:
                            console.print(f"  [red]✗ Failed to re-register {name}: {e}[/red]")

            console.print(f"\n[green]Fixed {fixed}/{len(issues)} issues[/green]")
        else:
            console.print("\n[dim]Run with --fix to attempt automatic repairs[/dim]")
    else:
        console.print("\n[bold green]No issues found. System healthy![/bold green]")


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
def status(
    json_output: bool = typer.Option(False, "--json", "-j", help="Output as JSON"),
    watch: int = typer.Option(0, "--watch", "-w", help="Refresh every N seconds (0=once)"),
) -> None:
    """Show overall system status."""
    init_db()

    def get_status() -> dict[str, Any]:
        results = {}

        # Linux
        result = _run_agent_action("linux", "system-health-check")
        results["linux"] = result

        # DevOps
        result = _run_agent_action("devops", "podman-status")
        results["podman"] = result

        result = _run_agent_action("devops", "docker-status")
        results["docker"] = result

        # Security
        result = _run_agent_action("security", "selinux-audit")
        results["selinux"] = result

        result = _run_agent_action("security", "firewall-audit")
        results["firewall"] = result

        # AI
        result = _run_agent_action("ai", "ollama-ping")
        results["ollama"] = result

        return results

    def print_status(results: dict[str, Any]) -> None:
        table = Table(title="Spectre Status", show_header=True)
        table.add_column("Component", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Details")

        for name, data in results.items():
            table.add_row(name.title(), data.get("status", "?"), data.get("log_output", ""))

        console.print(table)

    if watch > 0:
        console.print(f"[dim]Watching every {watch}s (Ctrl+C to stop)[/dim]")
        try:
            while True:
                results = get_status()
                if json_output:
                    import json
                    print(json.dumps(results, indent=2))
                else:
                    console.clear()
                    print_status(results)
                time.sleep(watch)
        except KeyboardInterrupt:
            console.print("\n[dim]Stopped watching.[/dim]")
    else:
        results = get_status()
        if json_output:
            import json
            print(json.dumps(results, indent=2))
        else:
            print_status(results)


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
    _get_engine()

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
    _get_engine()

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
def security(
    audit: bool = typer.Option(False, "--audit", help="Run full security audit"),
    fix: bool = typer.Option(False, "--fix", help="Auto-fix security issues"),
) -> None:
    """Security status and auditing."""
    init_db()

    if audit or fix:
        if audit:
            console.print(Panel("[bold]Running full security audit[/bold]", style="red"))
        actions = ["selinux-audit", "firewall-audit", "ports-audit", "secrets-scan", "ssh-audit"]
        issues = []
        for action in actions:
            result = _run_agent_action("security", action)
            _print_result(action, result)
            if (
                result.get("status") == "failed"
                or "WARNING" in result.get("log_output", "")
                or "CRITICAL" in result.get("log_output", "")
            ):
                issues.append({"action": action, "output": result.get("log_output", "")})

        if fix and issues:
            console.print(f"\n[bold]Found {len(issues)} security issue(s)[/bold]")
            console.print("[dim]Attempting fixes...[/dim]")
            fixed = 0

            for issue in issues:
                action = issue["action"]
                output = issue["output"]

                # SELinux permissive -> try to set to enforcing
                if action == "selinux-audit" and "Permissive" in output:
                    try:
                        import subprocess
                        res = subprocess.run(["sudo", "setenforce", "1"], capture_output=True, text=True, timeout=5)
                        if res.returncode == 0:
                            console.print("  [green]✓ Set SELinux to Enforcing[/green]")
                            fixed += 1
                        else:
                            console.print(f"  [red]✗ Failed to set SELinux: {res.stderr}[/red]")
                    except Exception as e:
                        console.print(f"  [red]✗ SELinux fix failed: {e}[/red]")

                # Firewall not running -> try to start
                elif action == "firewall-audit" and "not active" in output.lower():
                    try:
                        import subprocess
                        res = subprocess.run(
                            ["sudo", "systemctl", "start", "firewalld"],
                            capture_output=True, text=True, timeout=10,
                        )
                        if res.returncode == 0:
                            console.print("  [green]✓ Started firewalld[/green]")
                            fixed += 1
                        else:
                            console.print(f"  [red]✗ Failed to start firewalld: {res.stderr}[/red]")
                    except Exception as e:
                        console.print(f"  [red]✗ Firewalld fix failed: {e}[/red]")

                # SSH root login -> recommend manual fix
                elif action == "ssh-audit" and "root login" in output.lower():
                    console.print("  [yellow]![/yellow] SSH root login enabled - edit /etc/ssh/sshd_config manually")
                    console.print("    Set: PermitRootLogin no")

            console.print(f"\n[green]Fixed {fixed}/{len(issues)} issues[/green]")
        elif issues:
            console.print(f"\n[yellow]Found {len(issues)} security issue(s). Run with --fix to attempt repairs.[/yellow]")  # noqa: E501
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
    name: str | None = typer.Argument(None, help="Workflow name to run"),
    list_workflows: bool = typer.Option(False, "--list", help="List available workflows"),
    load_dir: str | None = typer.Option(None, "--load", help="Load custom workflows from directory"),
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
        for wf_name in engine.get_available_workflows():
            wf_type = "custom" if wf_name in engine.custom_workflows else "built-in"
            wf_def = all_defs.get(wf_name)
            description = descriptions.get(wf_name, wf_def.description if wf_def else "")
            table.add_row(wf_name, description, wf_type)
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
        raise typer.Exit(1) from e


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
    output: str | None = typer.Option(None, help="Output file path"),
) -> None:
    """Generate system reports."""
    init_db()
    _get_engine()

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
    get_key: str | None = typer.Option(None, "--get", help="Get a configuration value"),
    set_key: str | None = typer.Option(None, "--set", help="Set a configuration key"),
    set_value: str | None = typer.Option(None, "--value", help="Value to set (used with --set)"),
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
        from packages.memory.db import Configuration, save_configuration
        save_configuration(Configuration(key=set_key, value=set_value, profile=settings.profile))
        console.print(f"[green]Set {set_key} = {set_value}[/green]")
        return

    console.print("[dim]Use --show to display config, --get <key> to read, or --set <key> --value <val> to write[/dim]")


# ── events ────────────────────────────────────────────────────────────────────


@app.command()
def events(
    event_type: str | None = typer.Option(None, "--type", help="Filter by event type"),
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
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as get_version

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
    from packages.config.settings import DEFAULT_CONFIG_PATH, SpectreSettings, save_settings

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


# ── schedule ──────────────────────────────────────────────────────────────────


@app.command()
def schedule(
    action: str = typer.Argument("list", help="Action: list, add, remove, run"),
    name: str = typer.Option("", "--name", "-n", help="Task name"),
    cron: str = typer.Option("", "--cron", "-c", help="Cron expression (e.g., '0 2 * * *')"),
    interval: str = typer.Option("", "--interval", "-i", help="Interval (e.g., 'every 30m')"),
    workflow: str = typer.Option("", "--workflow", "-w", help="Workflow to run"),
) -> None:
    """Manage scheduled tasks."""
    import json

    from sqlmodel import Session, select

    from packages.core.scheduler import TaskScheduler
    from packages.memory.db import Configuration
    from packages.memory.db import engine as db_engine

    scheduler = TaskScheduler()

    # Load scheduled tasks from config
    with Session(db_engine) as session:
        config = session.exec(
            select(Configuration).where(Configuration.key == "scheduled_tasks")
        ).first()
        if config:
            try:
                tasks = json.loads(config.value)
                for task_name, task_config in tasks.items():
                    def make_callback(wf: str) -> Callable[[], Any]:
                        return lambda: _get_engine().run_workflow(wf)
                    scheduler.add_task(task_name, task_config["schedule"], make_callback(task_config["workflow"]))
            except Exception:
                pass

    if action == "list":
        tasks = scheduler.get_tasks()
        if not tasks:
            console.print("[dim]No scheduled tasks configured[/dim]")
            console.print("\n[yellow]Usage:[/yellow]")
            console.print("  spectre schedule add --name health --cron '0 * * * *' --workflow morning-startup")
            console.print("  spectre schedule add --name backup --interval 'every 6h' --workflow backup")
            return

        table = Table(title="Scheduled Tasks", show_header=True)
        table.add_column("Name", style="cyan")
        table.add_column("Schedule", style="green")
        table.add_column("Workflow")
        table.add_column("Enabled")
        table.add_column("Last Run")

        for task in tasks:
            from datetime import datetime

            last_run = (
                "Never" if task.last_run is None
                else datetime.fromtimestamp(task.last_run).strftime("%Y-%m-%d %H:%M")
            )
            table.add_row(
                task.name, task.schedule, getattr(task, 'workflow', '?'),
                "Yes" if task.enabled else "No", last_run,
            )
        console.print(table)

    elif action == "add":
        if not name or not workflow:
            console.print("[red]--name and --workflow are required[/red]")
            raise typer.Exit(1)
        if not cron and not interval:
            console.print("[red]--cron or --interval is required[/red]")
            raise typer.Exit(1)

        schedule_expr = cron if cron else interval

        # Save to config
        with Session(db_engine) as session:
            config = session.exec(
                select(Configuration).where(Configuration.key == "scheduled_tasks")
            ).first()
            tasks = json.loads(config.value) if config else {}
            tasks[name] = {"schedule": schedule_expr, "workflow": workflow, "enabled": True}
            if config:
                config.value = json.dumps(tasks)
                session.add(config)
            else:
                session.add(Configuration(key="scheduled_tasks", value=json.dumps(tasks), profile="default"))
            session.commit()

        console.print(f"[green]Added scheduled task '{name}': {schedule_expr} -> {workflow}[/green]")

    elif action == "remove":
        if not name:
            console.print("[red]--name is required[/red]")
            raise typer.Exit(1)

        with Session(db_engine) as session:
            config = session.exec(
                select(Configuration).where(Configuration.key == "scheduled_tasks")
            ).first()
            if config:
                tasks = json.loads(config.value)
                if name in tasks:
                    del tasks[name]
                    config.value = json.dumps(tasks)
                    session.add(config)
                    session.commit()
                    console.print(f"[green]Removed scheduled task '{name}'[/green]")
                else:
                    console.print(f"[yellow]Task '{name}' not found[/yellow]")
            else:
                console.print("[yellow]No scheduled tasks configured[/yellow]")

    elif action == "run":
        if not name:
            console.print("[red]--name is required[/red]")
            raise typer.Exit(1)

        # Find and run the task immediately
        with Session(db_engine) as session:
            config = session.exec(
                select(Configuration).where(Configuration.key == "scheduled_tasks")
            ).first()
            if config:
                tasks = json.loads(config.value)
                if name in tasks:
                    wf = tasks[name]["workflow"]
                    console.print(f"[dim]Running workflow '{wf}'...[/dim]")
                    result = _get_engine().run_workflow(wf)
                    status = result.get("status", "unknown")
                    icon = "[green]✓[/green]" if status == "success" else "[red]✗[/red]"
                    console.print(f"{icon} {name}: {status}")
                else:
                    console.print(f"[yellow]Task '{name}' not found[/yellow]")
            else:
                console.print("[yellow]No scheduled tasks configured[/yellow]")


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
    format: str = typer.Option("json", "--format", "-f", help="Output format: json, csv"),
) -> None:
    """Export Spectre data to JSON or CSV."""
    import csv
    import json

    init_db()
    from packages.memory.db import get_events, get_reports, get_workflow_runs

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
        from sqlmodel import Session, select

        from packages.memory.db import Configuration
        from packages.memory.db import engine as db_engine

        with Session(db_engine) as session:
            configs = list(session.exec(select(Configuration).limit(limit)))
        export_data["config"] = [{"key": c.key, "value": c.value, "profile": c.profile} for c in configs]

    if format == "csv":
        # CSV export - flatten all data into a single CSV
        output_path = Path(output)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".csv")

        rows = []
        for event in export_data.get("events", []):
            rows.append({
                "type": "event", "timestamp": event["timestamp"],
                "key": event["event_type"], "value": event.get("source", ""),
            })
        for report in export_data.get("reports", []):
            rows.append({
                "type": "report", "timestamp": report["timestamp"],
                "key": report["type"], "value": report["content"][:100],
            })
        for run in export_data.get("workflows", []):
            rows.append({
                "type": "workflow", "timestamp": run["timestamp"],
                "key": run["workflow"], "value": run["status"],
            })
        for config in export_data.get("config", []):
            rows.append({
                "type": "config", "timestamp": "", "key": config["key"], "value": config["value"],
            })

        if rows:
            with open(output_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["type", "timestamp", "key", "value"])
                writer.writeheader()
                writer.writerows(rows)
        console.print(f"[green]Exported {len(rows)} rows to {output_path}[/green]")
    else:
        # JSON export
        output_path = Path(output)
        if not output_path.suffix:
            output_path = output_path.with_suffix(".json")
        output_path.write_text(json.dumps(export_data, indent=2))
        console.print(f"[green]Exported data to {output_path}[/green]")
        n_events = len(export_data.get('events', []))
        n_reports = len(export_data.get('reports', []))
        n_workflows = len(export_data.get('workflows', []))
        n_config = len(export_data.get('config', []))
        console.print(f"[dim]Events: {n_events}, Reports: {n_reports}, Workflows: {n_workflows}, Config: {n_config}[/dim]")  # noqa: E501


# ── import ────────────────────────────────────────────────────────────────────


@app.command(name="import")
def import_data(
    input_file: str = typer.Argument(..., help="Input file to import"),
    data_type: str = typer.Option("all", "--type", "-t", help="Data type: all, events, reports, config"),
) -> None:
    """Import Spectre data from JSON."""
    import json

    input_path = Path(input_file)
    if not input_path.exists():
        console.print(f"[red]File not found: {input_file}[/red]")
        raise typer.Exit(1)

    try:
        data = json.loads(input_path.read_text())
    except json.JSONDecodeError as e:
        console.print(f"[red]Invalid JSON: {e}[/red]")
        raise typer.Exit(1) from e

    init_db()

    from packages.memory.db import (
        Configuration,
        EventLog,
        Report,
        save_event,
        save_report,
    )

    imported = {"events": 0, "reports": 0, "config": 0}

    if data_type in ("all", "events") and "events" in data:
        for event in data["events"]:
            try:
                save_event(EventLog(
                    event_type=event["event_type"],
                    source=event.get("source", "import"),
                    severity=event.get("severity", "info"),
                    data_json=json.dumps(event.get("data", {})),
                ))
                imported["events"] += 1
            except Exception:
                pass

    if data_type in ("all", "reports") and "reports" in data:
        for report in data["reports"]:
            try:
                save_report(Report(
                    report_type=report.get("type", "unknown"),
                    content=report.get("content", ""),
                    format="json",
                ))
                imported["reports"] += 1
            except Exception:
                pass

    if data_type in ("all", "config") and "config" in data:
        for config in data["config"]:
            try:
                from packages.memory.db import save_configuration
                save_configuration(Configuration(
                    key=config["key"],
                    value=config["value"],
                    profile=config.get("profile", "default"),
                ))
                imported["config"] += 1
            except Exception:
                pass

    total = sum(imported.values())
    console.print(f"[green]Imported {total} records from {input_file}[/green]")
    console.print(f"[dim]Events: {imported['events']}, Reports: {imported['reports']}, Config: {imported['config']}[/dim]")  # noqa: E501


# ── dashboard ─────────────────────────────────────────────────────────────────


@app.command()
def dashboard(
    refresh: int = typer.Option(5, "--refresh", "-r", help="Refresh interval in seconds"),
) -> None:
    """Interactive TUI dashboard."""
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.text import Text

    init_db()

    def build_dashboard() -> Layout:
        layout = Layout()
        layout.split_column(
            Layout(name="header", size=3),
            Layout(name="body"),
            Layout(name="footer", size=3),
        )
        layout["body"].split_row(
            Layout(name="left"),
            Layout(name="right"),
        )

        # Header
        header = Text(" Spectre Dashboard ", style="bold white on blue")
        layout["header"].update(Panel(header, style="blue"))

        # Left: System metrics
        try:
            linux_agent = _get_engine().resolve_agent("linux")
            metrics = linux_agent.observe() if linux_agent else {}
        except Exception:
            metrics = {}

        metrics_text = Text()
        metrics_text.append("System Metrics\n", style="bold cyan")
        metrics_text.append(f"CPU:     {metrics.get('cpu_percent', '?')}%\n")
        metrics_text.append(f"Memory:  {metrics.get('memory_percent', '?')}%\n")
        metrics_text.append(f"Swap:    {metrics.get('swap_percent', '?')}%\n")
        metrics_text.append(f"Disk:    {metrics.get('disk_percent', '?')}%\n")
        if metrics.get('battery_percent'):
            metrics_text.append(f"Battery: {metrics['battery_percent']}%\n")
        if metrics.get('temperature_c'):
            metrics_text.append(f"Temp:    {metrics['temperature_c']}°C\n")
        layout["left"].update(Panel(metrics_text, title="System"))

        # Right: Recent events
        from packages.memory.db import get_events
        events = get_events(limit=8)
        events_text = Text()
        events_text.append("Recent Events\n", style="bold cyan")
        for event in events:
            ts = event.timestamp.strftime("%H:%M")
            events_text.append(f"{ts} ", style="dim")
            events_text.append(f"{event.event_type} ", style="green")
            events_text.append(f"({event.source})\n")
        if not events:
            events_text.append("No events recorded\n", style="dim")
        layout["right"].update(Panel(events_text, title="Events"))

        # Footer
        footer = Text(f" Refreshing every {refresh}s | Press Ctrl+C to exit ", style="dim")
        layout["footer"].update(Panel(footer, style="dim"))

        return layout

    try:
        with Live(build_dashboard(), refresh_per_second=1/refresh, console=console) as live:
            while True:
                time.sleep(refresh)
                live.update(build_dashboard())
    except KeyboardInterrupt:
        console.print("\n[dim]Dashboard stopped.[/dim]")


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
