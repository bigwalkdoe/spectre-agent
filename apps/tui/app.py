"""Spectre TUI — multi-screen dashboard built on Textual.

Screens (switch with number keys, help with ``?``):

1. Dashboard — live CPU/memory/disk gauges with sparklines
2. Agents — registered agents, tools and execution history
3. Workflows — browse, run (background worker) and inspect run history
4. Security — audit checks executed in a background worker
5. Events — filterable live system event log
6. Reports — stored reports with a markdown viewer
7. Settings — active configuration summary
"""

from __future__ import annotations

import shutil
import time
from typing import TYPE_CHECKING, Any

from psutil import cpu_percent, disk_usage, sensors_battery, sensors_temperatures, virtual_memory
from rich.text import Text
from textual import on, work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, HorizontalGroup, Vertical
from textual.coordinate import Coordinate
from textual.screen import ModalScreen, Screen
from textual.widgets import (
    Button,
    DataTable,
    Label,
    Markdown,
    RichLog,
    Select,
    Sparkline,
    Static,
)

from packages.config.settings import load_settings
from packages.memory.db import (
    get_agent_records,
    get_events,
    get_reports,
    get_workflow_runs,
    init_db,
)

if TYPE_CHECKING:
    from packages.core.kernel import Kernel
    from packages.workflow_engine.engine import WorkflowEngine

# ── Shared helpers ────────────────────────────────────────────────────────────

_engine: WorkflowEngine | None = None
_kernel: Kernel | None = None


def get_engine() -> WorkflowEngine | None:
    """Return the shared WorkflowEngine, creating it lazily. None on failure."""
    global _engine
    if _engine is None:
        try:
            from apps.cli.main import _get_engine

            _engine = _get_engine()
        except Exception:
            return None
    return _engine


def get_kernel() -> Kernel | None:
    """Return the shared Kernel, creating it lazily. None on failure."""
    global _kernel
    if _kernel is None:
        try:
            from apps.cli.main import _get_kernel

            _kernel = _get_kernel()
        except Exception:
            return None
    return _kernel


def severity_style(severity: str) -> str:
    """Map a severity string to a rich style."""
    return {
        "error": "red",
        "critical": "bold red",
        "warning": "yellow",
        "success": "green",
    }.get(severity, "dim")


SHARED_CSS = """
Screen {
    background: $surface;
}
.section-title {
    text-style: bold;
    color: $accent;
    margin: 0 0 1 1;
}
DataTable {
    height: 1fr;
}
RichLog {
    height: 1fr;
    border: round $primary;
    padding: 0 1;
}
.actions {
    height: auto;
    margin: 1 0;
}
.status-line {
    height: 1;
    color: $text-muted;
    padding: 0 1;
}
Select {
    width: 30;
    margin-right: 1;
}
Button {
    margin-right: 1;
}
.bottom-row {
    height: 1fr;
}
.info-block {
    width: 2fr;
    border: round $secondary;
    padding: 0 1;
    margin-right: 1;
}
.events-block {
    width: 1fr;
    border: round $secondary;
    padding: 0 1;
}
"""


class MetricPanel(Static):
    """A labelled gauge with a sparkline history."""

    DEFAULT_CSS = """
    MetricPanel {
        height: 7;
        width: 1fr;
        border: round $primary;
        padding: 0 1;
    }
    """

    def __init__(self, title: str, warn_at: float, critical_at: float, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.panel_title = title
        self.warn_at = warn_at
        self.critical_at = critical_at
        self.history: list[float] = []

    def compose(self) -> ComposeResult:
        yield Label(self.panel_title, classes="stat-label")
        yield Label("—", classes="stat-value")
        yield Sparkline([])

    def update_value(self, value: float) -> None:
        """Push a new sample and re-render the gauge."""
        self.history.append(value)
        if len(self.history) > 120:
            del self.history[: len(self.history) - 120]
        level = "critical" if value >= self.critical_at else "warn" if value >= self.warn_at else "ok"
        color = {"ok": "green", "warn": "yellow", "critical": "red"}[level]
        self.styles.border = ("round", color)
        self.styles.border_title_color = color
        self.border_title = self.panel_title
        self.query_one(".stat-value", Label).update(f"{value:.1f}%")
        self.query_one(Sparkline).data = self.history[-60:]


# ── Screen 1: Dashboard ───────────────────────────────────────────────────────


class DashboardScreen(Screen):
    """Live system metrics with sparklines and a recent-events feed."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("System Overview", classes="section-title")
        with Horizontal():
            yield MetricPanel("CPU", 80, 95, id="panel-cpu")
            yield MetricPanel("Memory", 85, 95, id="panel-memory")
            yield MetricPanel("Disk", 90, 97, id="panel-disk")
        with Horizontal(classes="bottom-row"):
            yield RichLog(id="system-info", markup=True, wrap=True, classes="info-block")
            yield RichLog(id="dash-events", markup=True, classes="events-block")

    def on_mount(self) -> None:
        self._last_net: tuple[int, int] | None = None
        self._last_net_time: float = 0.0
        self.set_interval(2.0, self.refresh_metrics)
        self.set_interval(10.0, self.refresh_events)
        self.refresh_metrics()
        self.refresh_events()

    def action_refresh(self) -> None:
        self.refresh_metrics()
        self.refresh_events()
        self.notify("Dashboard refreshed", timeout=1)

    def refresh_metrics(self) -> None:
        try:
            cpu = cpu_percent(interval=None)
            mem = virtual_memory().percent
            disk = disk_usage("/").percent
            self.query_one("#panel-cpu", MetricPanel).update_value(cpu)
            self.query_one("#panel-memory", MetricPanel).update_value(mem)
            self.query_one("#panel-disk", MetricPanel).update_value(disk)

            lines: list[str] = []
            battery = sensors_battery()
            if battery:
                state = "discharging" if battery.power_plugged is False else "charging"
                lines.append(f"[b]Battery[/b] {battery.percent:.0f}%  ({state})")
            temps = sensors_temperatures()
            for name, entries in temps.items():
                if entries:
                    lines.append(f"[b]Temp[/b] {entries[0].current:.0f}°C ({name})")
                    break
            total_gb = shutil.disk_usage("/").total / 1024**3
            lines.append(f"[b]Disk total[/b] {total_gb:.0f} GiB ({disk:.0f}% used)")

            import psutil as _psutil

            net = _psutil.net_io_counters()
            now = time.monotonic()
            if self._last_net and self._last_net_time:
                dt = now - self._last_net_time
                if dt > 0:
                    sent = (net.bytes_sent - self._last_net[0]) / dt / 1024
                    recv = (net.bytes_recv - self._last_net[1]) / dt / 1024
                    lines.append(f"[b]Network[/b] ↑ {sent:.0f} KB/s   ↓ {recv:.0f} KB/s")
            self._last_net = (net.bytes_sent, net.bytes_recv)
            self._last_net_time = now

            kernel = get_kernel()
            if kernel:
                lines.append(f"[b]Kernel[/b] {'running' if kernel.running else 'stopped'}")

            info = self.query_one("#system-info", RichLog)
            info.clear()
            for line in lines:
                info.write(line)
        except Exception:
            pass

    def refresh_events(self) -> None:
        try:
            log = self.query_one("#dash-events", RichLog)
            log.clear()
            log.write("[b]Recent events[/b]")
            for event in reversed(get_events(limit=10)):
                style = severity_style(event.severity)
                log.write(f"[{style}]{event.timestamp:%H:%M:%S} {event.event_type}[/] [dim]({event.source})[/]")
        except Exception:
            pass


# ── Screen 2: Agents ──────────────────────────────────────────────────────────


class AgentsScreen(Screen):
    """Registered agents with their tools and recent execution history."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("Agents", classes="section-title")
        yield DataTable(id="agents-table", cursor_type="row")
        yield Label("", id="agents-status", classes="status-line")
        yield Label("Recent executions", classes="section-title")
        yield DataTable(id="agent-history-table", cursor_type="row")

    def on_mount(self) -> None:
        self.query_one("#agents-table", DataTable).add_columns("Agent", "Status", "Tools")
        self.query_one("#agent-history-table", DataTable).add_columns("Time", "Agent", "Action", "Status", "Duration")
        self.set_interval(10.0, self.refresh_agents)
        self.refresh_agents()

    def action_refresh(self) -> None:
        self.refresh_agents()
        self.notify("Agents refreshed", timeout=1)

    def refresh_agents(self) -> None:
        try:
            table = self.query_one("#agents-table", DataTable)
            table.clear()
            engine = get_engine()
            if engine is None:
                self.query_one("#agents-status", Label).update("Engine unavailable")
                return
            agents = engine.get_agents()
            for name, agent in agents.items():
                tools = ", ".join(getattr(agent, "tools", {}).keys())
                table.add_row(name, Text("● ready", style="green"), tools)
            self.query_one("#agents-status", Label).update(f"{len(agents)} agents registered")

            history = self.query_one("#agent-history-table", DataTable)
            history.clear()
            for record in reversed(get_agent_records(limit=15)):
                style = "green" if record.status == "success" else "red"
                history.add_row(
                    record.timestamp.strftime("%H:%M:%S"),
                    record.agent_name,
                    record.action,
                    Text(record.status, style=style),
                    f"{record.duration_ms} ms",
                )
        except Exception:
            pass


# ── Screen 3: Workflows ───────────────────────────────────────────────────────


class WorkflowsScreen(Screen):
    """Browse and run workflows; inspect recent execution history."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("Workflows", classes="section-title")
        yield DataTable(id="workflows-table", cursor_type="row")
        with HorizontalGroup(classes="actions"):
            yield Button("Run Selected", id="btn-run-workflow", variant="primary")
            yield Button("Refresh", id="btn-refresh-workflows")
        yield Label("Recent runs", classes="section-title")
        yield DataTable(id="runs-table", cursor_type="row")
        yield RichLog(id="workflow-log", markup=True, max_lines=200)

    def on_mount(self) -> None:
        self.query_one("#workflows-table", DataTable).add_columns("Workflow", "Description", "Type", "Steps")
        self.query_one("#runs-table", DataTable).add_columns("Time", "Workflow", "Status", "Duration")
        self.refresh_workflows()

    def action_refresh(self) -> None:
        self.refresh_workflows()
        self.notify("Workflows refreshed", timeout=1)

    def refresh_workflows(self) -> None:
        try:
            engine = get_engine()
            if engine is None:
                return
            table = self.query_one("#workflows-table", DataTable)
            table.clear()
            definitions = engine.get_workflow_definitions()
            custom = getattr(engine, "custom_workflows", {})
            for name in engine.get_available_workflows():
                wf = definitions.get(name)
                if wf is None:
                    continue
                wf_type = Text("custom", style="magenta") if name in custom else Text("built-in", style="cyan")
                table.add_row(name, (wf.description or "")[:60], wf_type, str(len(wf.steps)), key=name)

            runs = self.query_one("#runs-table", DataTable)
            runs.clear()
            for run in reversed(get_workflow_runs(limit=15)):
                style = "green" if run.status == "success" else "red"
                runs.add_row(
                    run.timestamp.strftime("%m-%d %H:%M"),
                    run.workflow,
                    Text(run.status, style=style),
                    f"{run.duration_ms} ms",
                )
        except Exception:
            pass

    def _log(self, message: str) -> None:
        self.query_one("#workflow-log", RichLog).write(message)

    @on(Button.Pressed, "#btn-refresh-workflows")
    def _refresh_pressed(self) -> None:
        self.refresh_workflows()

    @on(Button.Pressed, "#btn-run-workflow")
    def _run_pressed(self) -> None:
        table = self.query_one("#workflows-table", DataTable)
        if table.row_count == 0:
            self.notify("No workflow selected", severity="warning", timeout=2)
            return
        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        name = cell_key.row_key.value
        if not name:
            self.notify("No workflow selected", severity="warning", timeout=2)
            return
        self._run_workflow_worker(name)

    @work(thread=True, exclusive=True)
    def _run_workflow_worker(self, name: str) -> None:
        """Execute a workflow in a background thread; marshal log output back."""
        engine = get_engine()
        if engine is None:
            self.app.call_from_thread(self._log, "[red]Engine unavailable[/]")
            return
        self.app.call_from_thread(self._log, f"[b green]▶ Running workflow:[/] {name}")
        try:
            result = engine.run_workflow(name)
        except Exception as exc:
            self.app.call_from_thread(self._log, f"[red]✗ Workflow error:[/] {exc}")
            return
        status = result.get("status", "unknown")
        duration = result.get("duration_ms", 0)
        style = "green" if status == "success" else "red"
        self.app.call_from_thread(self._log, f"[b {style}]■ {name} finished:[/] {status} ({duration} ms)")
        steps = result.get("step_results", {})
        for step_key, step_result in steps.items():
            step_status = step_result.get("status", "?") if isinstance(step_result, dict) else "?"
            step_style = "green" if step_status == "success" else "red"
            self.app.call_from_thread(self._log, f"  [{step_style}]• {step_key}:[/] {step_status}")
        self.app.call_from_thread(self.refresh_workflows)


# ── Screen 4: Security ────────────────────────────────────────────────────────


class SecurityScreen(Screen):
    """Security audit checks executed in a background worker."""

    CHECKS = [
        ("SELinux", "selinux-audit"),
        ("Firewall", "firewall-audit"),
        ("Open Ports", "ports-audit"),
        ("Secrets Scan", "secrets-scan"),
        ("SSH Config", "ssh-audit"),
    ]

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("Security", classes="section-title")
        yield DataTable(id="security-table", cursor_type="row")
        with HorizontalGroup(classes="actions"):
            yield Button("Run Audit", id="btn-run-audit", variant="warning")
            yield Button("Refresh", id="btn-refresh-security")
        yield Label("Idle — press Run Audit to check this machine", id="security-status", classes="status-line")

    def on_mount(self) -> None:
        self.query_one("#security-table", DataTable).add_columns("Check", "Status", "Details")

    def action_refresh(self) -> None:
        self.notify("Press Run Audit to re-check", timeout=1)

    def _set_status(self, message: str) -> None:
        self.query_one("#security-status", Label).update(message)

    @on(Button.Pressed, "#btn-refresh-security")
    def _refresh_pressed(self) -> None:
        self.notify("Press Run Audit to re-check", timeout=1)

    @on(Button.Pressed, "#btn-run-audit")
    def _audit_pressed(self) -> None:
        self._audit_worker()

    @work(thread=True, exclusive=True)
    def _audit_worker(self) -> None:
        """Run all security checks in a thread; each result updates the table."""
        from apps.cli.main import _run_agent_action

        table = self.query_one("#security-table", DataTable)
        self.app.call_from_thread(table.clear)
        self.app.call_from_thread(self._set_status, "Running security audit…")
        failed = 0
        for check_name, action in self.CHECKS:
            try:
                result = _run_agent_action("security", action)
            except Exception as exc:
                result = {"status": "failed", "message": str(exc)}
            if result.get("status") != "success":
                failed += 1

            def apply(check_name: str = check_name, result: dict[str, Any] = result) -> None:
                succeeded = result.get("status") == "success"
                style = "green" if succeeded else "red"
                symbol = "✓ pass" if succeeded else "✗ fail"
                details = str(result.get("log_output", result.get("message", "")))[:80]
                table.add_row(check_name, Text(symbol, style=style), details, key=check_name)

            self.app.call_from_thread(apply)
        summary = f"Audit complete: {len(self.CHECKS) - failed}/{len(self.CHECKS)} passed"
        self.app.call_from_thread(self._set_status, summary)
        self.app.call_from_thread(
            self.notify,
            summary,
            severity="warning" if failed else "information",
            timeout=3,
        )


# ── Screen 5: Events ──────────────────────────────────────────────────────────


class EventsScreen(Screen):
    """Filterable live system event log."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("System Events", classes="section-title")
        with HorizontalGroup(classes="actions"):
            yield Select[str](
                [
                    ("All severities", "all"),
                    ("Error", "error"),
                    ("Warning", "warning"),
                    ("Info", "info"),
                ],
                id="event-filter",
                prompt="Filter",
                allow_blank=True,
            )
            yield Button("Refresh", id="btn-refresh-events")
        yield RichLog(id="events-log", markup=True, max_lines=1000)

    def on_mount(self) -> None:
        self.refresh_events()
        self.set_interval(10.0, self.refresh_events)

    def action_refresh(self) -> None:
        self.refresh_events()
        self.notify("Events refreshed", timeout=1)

    @on(Select.Changed, "#event-filter")
    def _filter_changed(self) -> None:
        self.refresh_events()

    @on(Button.Pressed, "#btn-refresh-events")
    def _refresh_pressed(self) -> None:
        self.refresh_events()

    def refresh_events(self) -> None:
        try:
            severity = self.query_one("#event-filter", Select).value
            log = self.query_one("#events-log", RichLog)
            log.clear()
            events = get_events(limit=200)
            if severity and severity != "all":
                events = [event for event in events if event.severity == severity]
            for event in reversed(events[-100:]):
                style = severity_style(event.severity)
                log.write(
                    f"[{style}]{event.timestamp:%Y-%m-%d %H:%M:%S}[/] "
                    f"[b]{event.event_type}[/] [dim]({event.source})[/] "
                    f"{event.data_json[:120]}"
                )
        except Exception:
            pass


# ── Screen 6: Reports ─────────────────────────────────────────────────────────


class ReportsScreen(Screen):
    """Stored reports with a markdown viewer."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("Reports", classes="section-title")
        yield DataTable(id="reports-table", cursor_type="row")
        with HorizontalGroup(classes="actions"):
            yield Button("View", id="btn-view-report", variant="primary")
            yield Button("Refresh", id="btn-refresh-reports")
        yield Markdown(id="report-content")

    def on_mount(self) -> None:
        self.query_one("#reports-table", DataTable).add_columns("ID", "Type", "Timestamp", "Format")
        self.refresh_reports()

    def action_refresh(self) -> None:
        self.refresh_reports()
        self.notify("Reports refreshed", timeout=1)

    def refresh_reports(self) -> None:
        try:
            table = self.query_one("#reports-table", DataTable)
            table.clear()
            for report in get_reports(limit=30):
                table.add_row(
                    str(report.id or ""),
                    report.report_type,
                    report.timestamp.strftime("%Y-%m-%d %H:%M"),
                    report.format,
                    key=str(report.id),
                )
        except Exception:
            pass

    @on(Button.Pressed, "#btn-refresh-reports")
    def _refresh_pressed(self) -> None:
        self.refresh_reports()

    @on(Button.Pressed, "#btn-view-report")
    def _view_pressed(self) -> None:
        self._show_selected()

    def _show_selected(self) -> None:
        table = self.query_one("#reports-table", DataTable)
        if table.row_count == 0:
            self.notify("No reports available", severity="warning", timeout=2)
            return
        cell_key = table.coordinate_to_cell_key(Coordinate(table.cursor_row, 0))
        report_id = cell_key.row_key.value
        report = next((r for r in get_reports(limit=50) if str(r.id) == report_id), None)
        if report is None:
            self.notify("Report not found", severity="error", timeout=2)
            return
        self.query_one("#report-content", Markdown).update(report.content)
        self.notify(f"Loaded report #{report_id}", timeout=1)


# ── Screen 7: Settings ────────────────────────────────────────────────────────


class SettingsScreen(Screen):
    """Read-only view of the active configuration."""

    BINDINGS = [Binding("r", "refresh", "Refresh")]

    def compose(self) -> ComposeResult:
        yield Label("Configuration", classes="section-title")
        yield DataTable(id="settings-table")
        yield Label("Edit with: spectre config --set <key> <value>", classes="status-line")

    def on_mount(self) -> None:
        self.query_one("#settings-table", DataTable).add_columns("Setting", "Value")
        self.refresh_settings()

    def action_refresh(self) -> None:
        self.refresh_settings()
        self.notify("Settings refreshed", timeout=1)

    def refresh_settings(self) -> None:
        try:
            settings = load_settings()
            table = self.query_one("#settings-table", DataTable)
            table.clear()
            items = [
                ("Profile", settings.profile),
                ("Log level", settings.log_level),
                ("Ollama URL", settings.ollama.url),
                ("Ollama model", settings.ollama.benchmark_model),
                ("Monitoring interval", f"{settings.monitoring.interval_seconds}s"),
                ("Monitoring enabled", str(settings.monitoring.enabled)),
            ]
            for key, value in items:
                table.add_row(key, str(value))
        except Exception:
            pass


# ── Help modal ────────────────────────────────────────────────────────────────


class HelpScreen(ModalScreen[None]):
    """Modal keybinding reference."""

    BINDINGS = [Binding("escape", "dismiss", "Close"), Binding("q", "dismiss", "Close")]

    DEFAULT_CSS = """
    HelpScreen {
        align: center middle;
    }
    #help-dialog {
        width: 60;
        height: auto;
        max-height: 80%;
        border: round $accent;
        background: $surface;
        padding: 1 2;
    }
    """

    def compose(self) -> ComposeResult:
        table: DataTable[str] = DataTable()
        table.add_columns("Key", "Action")
        for key, action in [
            ("1 … 7", "Switch screens"),
            ("r", "Refresh current screen"),
            ("d", "Toggle dark / light mode"),
            ("?", "Show this help"),
            ("q", "Quit Spectre TUI"),
        ]:
            table.add_row(Text(key, style="bold cyan"), action)  # type: ignore[arg-type]
        with Vertical(id="help-dialog"):
            yield Label("Spectre TUI — Keybindings", classes="section-title")
            yield table


# ── Main application ──────────────────────────────────────────────────────────


class SpectreTUI(App[None]):
    """Spectre TUI application."""

    TITLE = "Spectre — System Maintenance Agent"
    SUB_TITLE = "AI Engineering Operating System"

    CSS = SHARED_CSS

    SCREENS = {
        "dashboard": DashboardScreen,
        "agents": AgentsScreen,
        "workflows": WorkflowsScreen,
        "security": SecurityScreen,
        "events": EventsScreen,
        "reports": ReportsScreen,
        "settings": SettingsScreen,
    }

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("d", "toggle_dark", "Dark Mode"),
        Binding("question_mark", "help", "Help", key_display="?"),
        Binding("1", "switch_screen('dashboard')", "Dashboard", show=False),
        Binding("2", "switch_screen('agents')", "Agents", show=False),
        Binding("3", "switch_screen('workflows')", "Workflows", show=False),
        Binding("4", "switch_screen('security')", "Security", show=False),
        Binding("5", "switch_screen('events')", "Events", show=False),
        Binding("6", "switch_screen('reports')", "Reports", show=False),
        Binding("7", "switch_screen('settings')", "Settings", show=False),
    ]

    def on_mount(self) -> None:
        init_db()
        # Textual 8.x: switch_screen/pop_screen against the auto-created default
        # screen during startup crashes (_pop_result_callback on an empty stack),
        # so we simply push the dashboard on top of it instead.
        self.push_screen("dashboard")

    def action_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_toggle_dark(self) -> None:
        # Textual 8.x: dark mode is theme-based (no `dark` reactive).
        self.theme = "textual-light" if self.theme == "textual-dark" else "textual-dark"
        self.notify(f"Theme: {self.theme}", timeout=1)


def run_tui(refresh: int = 5) -> None:
    """Entry point for the TUI. ``refresh`` is kept for CLI compatibility."""
    app = SpectreTUI()
    app.run()
