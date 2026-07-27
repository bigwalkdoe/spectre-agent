"""Enterprise-grade TUI for Spectre using Textual."""

from __future__ import annotations

from collections import deque
from typing import TYPE_CHECKING, Any

from rich.columns import Columns
from rich.panel import Panel
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.reactive import reactive
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    ListItem,
    ListView,
    Log,
    Markdown,
    Select,
    Sparkline,
    Static,
)

from packages.config.settings import load_settings
from packages.memory.db import (
    get_events,
    get_reports,
    init_db,
)

if TYPE_CHECKING:
    from packages.core.kernel import Kernel
    from packages.workflow_engine.engine import WorkflowEngine


class MetricsWidget(Static):
    """Real-time system metrics display with sparklines."""

    cpu_history: reactive[deque[float]] = reactive(deque(maxlen=60))
    mem_history: reactive[deque[float]] = reactive(deque(maxlen=60))
    disk_history: reactive[deque[float]] = reactive(deque(maxlen=60))
    net_sent_history: reactive[deque[float]] = reactive(deque(maxlen=60))
    net_recv_history: reactive[deque[float]] = reactive(deque(maxlen=60))

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.engine: WorkflowEngine | None = None
        self._last_net: Any = None

    def on_mount(self) -> None:
        self.set_interval(2, self.update_metrics)

    def update_metrics(self) -> None:
        if not self.engine:
            from apps.cli.main import _get_engine
            self.engine = _get_engine()

        try:
            linux_agent = self.engine.resolve_agent("linux")
            if linux_agent:
                metrics = linux_agent.observe()
                self.cpu_history.append(metrics.get("cpu_percent", 0))
                self.mem_history.append(metrics.get("memory_percent", 0))
                self.disk_history.append(metrics.get("disk_percent", 0))

                import psutil
                net = psutil.net_io_counters()
                if self._last_net:
                    sent_mb = (net.bytes_sent - self._last_net.bytes_sent) / 1024 / 1024
                    recv_mb = (net.bytes_recv - self._last_net.bytes_recv) / 1024 / 1024
                    self.net_sent_history.append(sent_mb)
                    self.net_recv_history.append(recv_mb)
                self._last_net = net

                self.refresh()
        except Exception:
            pass

    def render(self) -> Columns:
        from rich.columns import Columns

        cpu_val = self.cpu_history[-1] if self.cpu_history else 0
        mem_val = self.mem_history[-1] if self.mem_history else 0
        disk_val = self.disk_history[-1] if self.disk_history else 0

        cpu_spark = Sparkline(list(self.cpu_history))
        mem_spark = Sparkline(list(self.mem_history))
        disk_spark = Sparkline(list(self.disk_history))

        panels = [
            Panel(
                f"[bold cyan]{cpu_val:.1f}%[/]\n{cpu_spark}",
                title="CPU",
                border_style="red" if cpu_val > 80 else "green",
                width=35,
            ),
            Panel(
                f"[bold cyan]{mem_val:.1f}%[/]\n{mem_spark}",
                title="Memory",
                border_style="red" if mem_val > 85 else "green",
                width=35,
            ),
            Panel(
                f"[bold cyan]{disk_val:.1f}%[/]\n{disk_spark}",
                title="Disk",
                border_style="red" if disk_val > 90 else "green",
                width=35,
            ),
        ]

        if self.net_sent_history:
            net_sent = Sparkline(list(self.net_sent_history))
            net_recv = Sparkline(list(self.net_recv_history))
            panels.append(
                Panel(
                    f"[green]↑ {self.net_sent_history[-1]:.2f} MB/s[/]\n{net_sent}\n"
                    f"[red]↓ {self.net_recv_history[-1]:.2f} MB/s[/]\n{net_recv}",
                    title="Network",
                    border_style="blue",
                    width=35,
                )
            )

        return Columns(panels, equal=True, expand=True)


class AgentStatusWidget(Static):
    """Agent status and quick actions."""

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.engine: WorkflowEngine | None = None

    def on_mount(self) -> None:
        self.set_interval(5, self.refresh)

    def compose(self) -> ComposeResult:
        yield DataTable(id="agents-table")

    def on_ready(self) -> None:
        if not self.engine:
            from apps.cli.main import _get_engine
            self.engine = _get_engine()
        self.update_table()

    def update_table(self) -> None:
        try:
            table = self.query_one("#agents-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Agent", "Status", "Actions", "Last Run")

            if self.engine:
                for name, agent in self.engine.agents.items():
                    status = "🟢 Ready"
                    actions = ", ".join(getattr(agent, "tools", {}).keys()) if hasattr(agent, "tools") else "N/A"
                    table.add_row(name, status, actions, "Never")
        except Exception:
            pass


class WorkflowPanel(Static):
    """Workflow execution and monitoring."""

    def compose(self) -> ComposeResult:
        yield Label("Workflows", classes="section-title")
        yield DataTable(id="workflows-table")
        yield Horizontal(
            Button("Run Selected", id="run-workflow", variant="primary"),
            Button("View Details", id="view-workflow"),
            Button("Load Custom", id="load-workflow"),
        )
        yield Log(id="workflow-log", max_lines=20)

    def on_mount(self) -> None:
        self.update_workflows()

    def update_workflows(self) -> None:
        try:
            from apps.cli.main import _get_engine
            engine = _get_engine()
            table = self.query_one("#workflows-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Workflow", "Description", "Type", "Steps")

            for name in engine.get_available_workflows():
                wf_def = engine.get_workflow_definitions().get(name)
                if wf_def:
                    wf_type = "Custom" if name in engine.custom_workflows else "Built-in"
                    table.add_row(name, wf_def.description[:50], wf_type, str(len(wf_def.steps)))
        except Exception:
            pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "run-workflow":
            self.run_selected_workflow()
        elif event.button.id == "view-workflow":
            self.view_workflow_details()
        elif event.button.id == "load-workflow":
            self.load_custom_workflow()

    def run_selected_workflow(self) -> None:
        log = self.query_one("#workflow-log", Log)
        log.write_line("[bold green]Starting workflow...[/]")
        # Implementation would run the workflow asynchronously

    def view_workflow_details(self) -> None:
        log = self.query_one("#workflow-log", Log)
        log.write_line("[bold cyan]Viewing workflow details...[/]")

    def load_custom_workflow(self) -> None:
        log = self.query_one("#workflow-log", Log)
        log.write_line("[bold cyan]Loading custom workflow...[/]")


class SecurityWidget(Static):
    """Security alerts and audit results."""

    def compose(self) -> ComposeResult:
        yield Label("Security Status", classes="section-title")
        yield DataTable(id="security-table")
        yield Button("Run Full Audit", id="security-audit", variant="warning")

    def on_mount(self) -> None:
        self.update_security()

    def update_security(self) -> None:
        try:
            table = self.query_one("#security-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Check", "Status", "Details")

            from apps.cli.main import _run_agent_action
            checks = [
                ("SELinux", "selinux-audit"),
                ("Firewall", "firewall-audit"),
                ("Open Ports", "ports-audit"),
                ("Secrets Scan", "secrets-scan"),
                ("SSH Config", "ssh-audit"),
            ]

            for name, action in checks:
                result = _run_agent_action("security", action)
                status = "🟢 Pass" if result.get("status") == "success" else "🔴 Fail"
                details = result.get("log_output", "")[:60]
                table.add_row(name, status, details)
        except Exception:
            pass


class SystemLogWidget(Static):
    """Real-time system log viewer."""

    def compose(self) -> ComposeResult:
        yield Horizontal(
            Select([("All", "all"), ("Errors", "error"), ("Warnings", "warning"), ("Info", "info")],
                   id="log-filter", prompt="Filter"),
            Input(placeholder="Search...", id="log-search"),
        )
        yield Log(id="system-log", max_lines=1000)

    def on_mount(self) -> None:
        self.set_interval(3, self.refresh_logs)
        self.refresh_logs()

    def refresh_logs(self) -> None:
        try:
            log_widget = self.query_one("#system-log", Log)
            events = get_events(limit=50)
            log_widget.clear()
            for event in reversed(events):
                style = "red" if event.severity == "error" else "yellow" if event.severity == "warning" else "white"
                log_widget.write_line(
                    f"[{event.timestamp.strftime('%H:%M:%S')}] "
                    f"[{style}]{event.event_type}[/] "
                    f"({event.source}): {event.data_json[:100]}"
                )
        except Exception:
            pass


class SettingsPanel(Static):
    """Configuration management."""

    def compose(self) -> ComposeResult:
        yield Label("Configuration", classes="section-title")
        yield DataTable(id="config-table")
        yield Horizontal(
            Button("Save", id="save-config", variant="primary"),
            Button("Reload", id="reload-config"),
        )

    def on_mount(self) -> None:
        self.update_config()

    def update_config(self) -> None:
        try:
            settings = load_settings()
            table = self.query_one("#config-table", DataTable)
            table.clear(columns=True)
            table.add_columns("Key", "Value")

            config_items = [
                ("Profile", settings.profile),
                ("Log Level", settings.log_level),
                ("Ollama URL", settings.ollama.url),
                ("Ollama Model", settings.ollama.benchmark_model),
                ("Monitoring Interval", f"{settings.monitoring.interval_seconds}s"),
                ("Monitoring Enabled", str(settings.monitoring.enabled)),
            ]

            for key, value in config_items:
                table.add_row(key, str(value))
        except Exception:
            pass


class ReportViewer(Static):
    """View generated reports."""

    def compose(self) -> ComposeResult:
        yield Label("Reports", classes="section-title")
        yield DataTable(id="reports-table")
        yield Horizontal(
            Button("View", id="view-report", variant="primary"),
            Button("Export", id="export-report"),
            Button("Delete", id="delete-report", variant="error"),
        )
        yield Markdown(id="report-content")

    def on_mount(self) -> None:
        self.update_reports()

    def update_reports(self) -> None:
        try:
            table = self.query_one("#reports-table", DataTable)
            table.clear(columns=True)
            table.add_columns("ID", "Type", "Timestamp", "Format")

            reports = get_reports(limit=20)
            for r in reports:
                table.add_row(str(r.id), r.report_type, r.timestamp.strftime("%Y-%m-%d %H:%M"), r.format)
        except Exception:
            pass


class SpectreTUI(App):
    """Main Spectre TUI Application."""

    CSS = (
        "    Screen {\n"
        "        background: $surface;\n"
        "    }\n"
        "    .section-title {\n"
        "        text-style: bold;\n"
        "        color: $accent;\n"
        "        margin-bottom: 1;\n"
        "    }\n"
        "    DataTable {\n"
        "        height: 1fr;\n"
        "    }\n"
        "    Log {\n"
        "        height: 1fr;\n"
        "        border: solid $primary;\n"
        "    }\n"
        "    #workflow-log {\n"
        "        height: 15;\n"
        "        border: solid $secondary;\n"
        "    }\n"
        "    Markdown {\n"
        "        height: 1fr;\n"
        "        border: solid $primary;\n"
        "        padding: 1;\n"
        "    }\n"
        "    Button {\n"
        "        margin-right: 1;\n"
        "    }\n"
        "    Horizontal {\n"
        "        height: auto;\n"
        "    }\n"
        "    .sidebar {\n"
        "        width: 30;\n"
        "        border-right: solid $primary;\n"
        "        padding: 1;\n"
        "    }\n"
        "    .main-content {\n"
        "        width: 1fr;\n"
        "        padding: 1;\n"
        "    }\n"
        "    .tab-labels {\n"
        "        text-style: bold;\n"
        "        color: $accent;\n"
        "        margin-bottom: 1;\n"
        "    }\n"
        "    .tab-buttons {\n"
        "        height: auto;\n"
        "    }\n"
        "    .tab-buttons Button {\n"
        "        margin-right: 1;\n"
        "    }\n"
        "    .hidden {\n"
        "        display: none;\n"
        "    }\n"
        "    .visible {\n"
        "        display: block;\n"
        "    }\n"
    )

    BINDINGS = [
        Binding("q", "quit", "Quit"),
        Binding("r", "refresh", "Refresh"),
        Binding("d", "toggle_dark", "Dark Mode"),
        Binding("1", "focus_tab('dashboard')", "Dashboard"),
        Binding("2", "focus_tab('agents')", "Agents"),
        Binding("3", "focus_tab('workflows')", "Workflows"),
        Binding("4", "focus_tab('security')", "Security"),
        Binding("5", "focus_tab('logs')", "Logs"),
        Binding("6", "focus_tab('reports')", "Reports"),
        Binding("7", "focus_tab('settings')", "Settings"),
        Binding("ctrl+c", "quit", "Quit"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.engine: WorkflowEngine | None = None
        self.kernel: Kernel | None = None
        self.dark = True

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Container(
            Horizontal(
                Vertical(
                    Static("SPECTRE", classes="title"),
                    Label("System Maintenance OS", classes="subtitle"),
                    ListView(
                        ListItem(Label("📊 Dashboard"), id="nav-dashboard"),
                        ListItem(Label("🤖 Agents"), id="nav-agents"),
                        ListItem(Label("⚙️ Workflows"), id="nav-workflows"),
                        ListItem(Label("🔒 Security"), id="nav-security"),
                        ListItem(Label("📝 Logs"), id="nav-logs"),
                        ListItem(Label("📋 Reports"), id="nav-reports"),
                        ListItem(Label("⚙️ Settings"), id="nav-settings"),
                    ),
                    classes="sidebar",
                ),
                Vertical(
                    Label("Tabs:", classes="tab-labels"),
                    Horizontal(
                        Button("Dashboard", id="btn-tab-dashboard", variant="primary"),
                        Button("Agents", id="btn-tab-agents"),
                        Button("Workflows", id="btn-tab-workflows"),
                        Button("Security", id="btn-tab-security"),
                        Button("Logs", id="btn-tab-logs"),
                        Button("Reports", id="btn-tab-reports"),
                        Button("Settings", id="btn-tab-settings"),
                        classes="tab-buttons",
                    ),
                    Container(
                        MetricsWidget(),
                        AgentStatusWidget(),
                        id="tab-dashboard",
                    ),
                    AgentStatusWidget(id="tab-agents", classes="hidden"),
                    WorkflowPanel(id="tab-workflows", classes="hidden"),
                    SecurityWidget(id="tab-security", classes="hidden"),
                    SystemLogWidget(id="tab-logs", classes="hidden"),
                    ReportViewer(id="tab-reports", classes="hidden"),
                    SettingsPanel(id="tab-settings", classes="hidden"),
                    classes="main-content",
                ),
            ),
        )
        yield Footer()

    def on_mount(self) -> None:
        init_db()
        from apps.cli.main import _get_engine, _get_kernel
        self.engine = _get_engine()
        self.kernel = _get_kernel()

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        """Handle sidebar navigation selection."""
        tab_map = {
            "nav-dashboard": "tab-dashboard",
            "nav-agents": "tab-agents",
            "nav-workflows": "tab-workflows",
            "nav-security": "tab-security",
            "nav-logs": "tab-logs",
            "nav-reports": "tab-reports",
            "nav-settings": "tab-settings",
        }
        if event.item.id in tab_map:
            self._switch_tab(tab_map[event.item.id])

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle tab button presses."""
        tab_map = {
            "nav-dashboard": "tab-dashboard",
            "nav-agents": "tab-agents",
            "nav-workflows": "tab-workflows",
            "nav-security": "tab-security",
            "nav-logs": "tab-logs",
            "nav-reports": "tab-reports",
            "nav-settings": "tab-settings",
            "btn-tab-settings": "tab-settings",
        }
        if event.button.id in tab_map:
            self._switch_tab(tab_map[event.button.id])

    def _switch_tab(self, tab_id: str) -> None:
        """Switch visible tab by toggling hidden classes."""
        # Hide all tabs
        for widget in self.query(
            "#tab-dashboard, #tab-agents, #tab-workflows, #tab-security, #tab-logs, #tab-reports, #tab-settings"
        ):
            widget.add_class("hidden")
        # Show selected tab
        self.query_one(f"#{tab_id}").remove_class("hidden")

    def action_refresh(self) -> None:
        self.notify("Refreshing...", timeout=1)
        for widget in self.walk_children():
            if hasattr(widget, "on_mount"):
                widget.on_mount()

    def action_focus_tab(self, tab_id: str) -> None:
        self._switch_tab(tab_id)

    def action_toggle_dark(self) -> None:
        self.dark = not self.dark
        self.notify(f"Dark mode: {'on' if self.dark else 'off'}")


def run_tui(refresh: int = 5) -> None:
    """Entry point for the TUI."""
    app = SpectreTUI()
    app.run()