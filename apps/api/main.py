"""Spectre API — FastAPI REST backend for programmatic access."""

from __future__ import annotations

import json
import os
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Security
from fastapi.responses import HTMLResponse
from fastapi.security import APIKeyHeader

from packages.config.settings import load_settings
from packages.core.kernel import Kernel
from packages.core.service_bus import ServiceBus
from packages.memory.db import (
    Configuration,
    get_configuration,
    get_decisions,
    get_reports,
    get_workflow_runs,
    init_db,
    save_configuration,
)
from packages.workflow_engine.engine import WorkflowEngine

app = FastAPI(title="Spectre API", version="0.2.0")
engine: WorkflowEngine | None = None
kernel: Kernel | None = None
service_bus: ServiceBus | None = None

# API Key authentication
API_KEY = os.environ.get("SPECTRE_API_KEY", "")
API_KEY_HEADER = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_key(api_key: str | None = Security(API_KEY_HEADER)) -> bool:
    """Verify API key if configured."""
    if not API_KEY:
        return True  # No API key configured, allow all
    if api_key == API_KEY:
        return True
    raise HTTPException(status_code=401, detail="Invalid API key")


def _get_engine() -> WorkflowEngine:
    global engine
    if engine is None:
        settings = load_settings()
        bus = _get_service_bus()
        kernel = _get_kernel()
        engine = WorkflowEngine(config={"ollama_url": settings.ollama.url}, service_bus=bus, event_bus=kernel.event_bus)
    return engine


def _get_kernel() -> Kernel:
    global kernel
    if kernel is None:
        kernel = Kernel()
    return kernel


def _get_service_bus() -> ServiceBus:
    global service_bus
    if service_bus is None:
        service_bus = ServiceBus()
    return service_bus


@app.on_event("startup")
async def startup() -> None:
    init_db()


# ── Agents ────────────────────────────────────────────────────────────────────


@app.get("/api/agents")
async def list_agents(_: bool = Depends(verify_api_key)) -> dict[str, list[str]]:
    """List all registered agents."""
    eng = _get_engine()
    return {"agents": list(eng.agents.keys())}


@app.get("/api/agents/{agent_name}")
async def get_agent_status(agent_name: str, _: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Get status/metrics from a specific agent."""
    eng = _get_engine()
    agent = eng.resolve_agent(agent_name)
    if not agent:
        raise HTTPException(404, f"Agent '{agent_name}' not found")
    return agent.observe()


# ── Workflows ─────────────────────────────────────────────────────────────────


@app.get("/api/workflows")
async def list_workflows(_: bool = Depends(verify_api_key)) -> dict[str, list[str]]:
    """List available workflows."""
    eng = _get_engine()
    return {"workflows": eng.get_available_workflows()}


@app.post("/api/workflows/{name}")
async def run_workflow(name: str, _: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Execute a workflow by name."""
    eng = _get_engine()
    try:
        result = eng.run_workflow(name)
        return result
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.get("/api/workflows/history")
async def workflow_history(limit: int = 50, _: bool = Depends(verify_api_key)) -> list[dict[str, Any]]:
    """Get workflow run history."""
    runs = get_workflow_runs(limit=limit)
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "workflow": r.workflow,
            "status": r.status,
            "duration_ms": r.duration_ms,
        }
        for r in runs
    ]


@app.get("/api/workflows/definitions")
async def workflow_definitions(_: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Get all workflow definitions (built-in + custom)."""
    eng = _get_engine()
    defs = eng.get_workflow_definitions()
    return {
        name: {
            "name": wf.name,
            "description": wf.description,
            "steps": [{"agent": s.agent, "action": s.action} for s in wf.steps],
            "continue_on_failure": wf.continue_on_failure,
        }
        for name, wf in defs.items()
    }


@app.post("/api/workflows/load")
async def load_workflows(directory: str, _: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Load custom workflows from a directory."""
    from pathlib import Path
    eng = _get_engine()
    try:
        count = eng.load_workflows(Path(directory))
        return {"loaded": count, "directory": directory}
    except Exception as e:
        raise HTTPException(400, str(e)) from e


# ── System ────────────────────────────────────────────────────────────────────


@app.get("/api/health")
async def health_check() -> dict[str, str]:
    """API health check."""
    return {"status": "ok"}


@app.get("/api/version")
async def get_version() -> dict[str, str]:
    """Get Spectre version."""
    from importlib.metadata import PackageNotFoundError
    from importlib.metadata import version as get_version
    try:
        spectre_version = get_version("spectre")
    except PackageNotFoundError:
        spectre_version = "0.2.0-dev"
    return {"version": spectre_version, "api": "0.2.0"}


# ── Core ──────────────────────────────────────────────────────────────────────


@app.get("/api/core/kernel")
async def kernel_status(_: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Get Kernel status."""
    k = _get_kernel()
    return {
        "running": k.running,
        "services": k.container.list_services(),
    }


@app.post("/api/core/kernel/start")
async def kernel_start(_: bool = Depends(verify_api_key)) -> dict[str, str]:
    """Start the Kernel."""
    k = _get_kernel()
    if k.running:
        return {"status": "already_running"}
    k.start()
    return {"status": "started"}


@app.post("/api/core/kernel/stop")
async def kernel_stop(_: bool = Depends(verify_api_key)) -> dict[str, str]:
    """Stop the Kernel."""
    k = _get_kernel()
    if not k.running:
        return {"status": "not_running"}
    k.stop()
    return {"status": "stopped"}


@app.get("/api/core/service-bus")
async def service_bus_status(_: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Get Service Bus status."""
    bus = _get_service_bus()
    return {
        "services": [{"name": s.name, "type": s.service_type, "metadata": s.metadata} for s in bus.list_services()],
        "topics": list(bus._handlers.keys()),
        "request_handlers": list(bus._request_handlers.keys()),
    }


@app.get("/api/events")
async def get_events(
    event_type: str | None = None,
    source: str | None = None,
    limit: int = 20,
    _: bool = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """Return recent events from the EventBus."""
    from packages.memory.db import get_events as db_get_events
    init_db()
    records = db_get_events(event_type=event_type, limit=limit)
    return [
        {
            "timestamp": e.timestamp.isoformat(),
            "event_type": e.event_type,
            "source": e.source,
            "severity": e.severity,
            "data": json.loads(e.data_json) if e.data_json else {},
        }
        for e in records
    ]


@app.get("/api/schedule")
async def list_schedule(_: bool = Depends(verify_api_key)) -> list[dict[str, Any]]:
    """List all scheduled tasks."""
    from sqlmodel import Session, select

    from packages.memory.db import Configuration
    from packages.memory.db import engine as db_engine

    with Session(db_engine) as session:
        config = session.exec(
            select(Configuration).where(Configuration.key == "scheduled_tasks")
        ).first()
        if not config:
            return []
        tasks = json.loads(config.value)
        return [
            {"name": name, "schedule": t["schedule"], "workflow": t["workflow"], "enabled": t.get("enabled", True)}
            for name, t in tasks.items()
        ]


@app.post("/api/schedule")
async def add_schedule(name: str, schedule: str, workflow: str, _: bool = Depends(verify_api_key)) -> dict[str, str]:
    """Add a scheduled task."""
    from sqlmodel import Session, select

    from packages.memory.db import Configuration
    from packages.memory.db import engine as db_engine

    with Session(db_engine) as session:
        config = session.exec(
            select(Configuration).where(Configuration.key == "scheduled_tasks")
        ).first()
        tasks = json.loads(config.value) if config else {}
        tasks[name] = {"schedule": schedule, "workflow": workflow, "enabled": True}
        if config:
            config.value = json.dumps(tasks)
            session.add(config)
        else:
            session.add(Configuration(key="scheduled_tasks", value=json.dumps(tasks), profile="default"))
        session.commit()
    return {"status": "added", "name": name}


@app.delete("/api/schedule/{name}")
async def remove_schedule(name: str, _: bool = Depends(verify_api_key)) -> dict[str, str]:
    """Remove a scheduled task."""
    from sqlmodel import Session, select

    from packages.memory.db import Configuration
    from packages.memory.db import engine as db_engine

    with Session(db_engine) as session:
        config = session.exec(
            select(Configuration).where(Configuration.key == "scheduled_tasks")
        ).first()
        if not config:
            raise HTTPException(404, "No scheduled tasks")
        tasks = json.loads(config.value)
        if name not in tasks:
            raise HTTPException(404, f"Task '{name}' not found")
        del tasks[name]
        config.value = json.dumps(tasks)
        session.add(config)
        session.commit()
    return {"status": "removed", "name": name}


@app.get("/api/system/status")
async def system_status() -> dict[str, Any]:
    """Get system status from all agents."""
    eng = _get_engine()
    statuses: dict[str, Any] = {}
    for name, agent in eng.agents.items():
        try:
            statuses[name] = agent.observe()
        except Exception:
            statuses[name] = {"error": "failed to observe"}
    return statuses


# ── Reports ───────────────────────────────────────────────────────────────────


@app.get("/api/reports")
async def list_reports(
    report_type: str | None = None,
    limit: int = 50,
    _: bool = Depends(verify_api_key),
) -> list[dict[str, Any]]:
    """List generated reports."""
    reports = get_reports(report_type=report_type, limit=limit)
    return [
        {
            "id": r.id,
            "timestamp": r.timestamp.isoformat(),
            "type": r.report_type,
            "format": r.format,
        }
        for r in reports
    ]


@app.get("/api/reports/{report_id}")
async def get_report(report_id: int, _: bool = Depends(verify_api_key)) -> dict[str, Any]:
    """Get a specific report by ID."""
    from sqlmodel import Session

    from packages.memory.db import Report, engine

    with Session(engine) as session:
        report = session.get(Report, report_id)
        if not report:
            raise HTTPException(404, "Report not found")
        return {
            "id": report.id,
            "timestamp": report.timestamp.isoformat(),
            "type": report.report_type,
            "format": report.format,
            "content": report.content,
        }


# ── Configuration ─────────────────────────────────────────────────────────────


@app.get("/api/config/{key}")
async def get_config(key: str, profile: str = "default", _: bool = Depends(verify_api_key)) -> dict[str, str]:
    """Get a configuration value."""
    value = get_configuration(key, profile)
    if value is None:
        raise HTTPException(404, f"Config '{key}' not found")
    return {"key": key, "value": value, "profile": profile}


@app.put("/api/config/{key}")
async def set_config(
    key: str,
    value: str,
    profile: str = "default",
    _: bool = Depends(verify_api_key),
) -> dict[str, str]:
    """Set a configuration value."""
    save_configuration(Configuration(key=key, value=value, profile=profile))
    return {"key": key, "value": value, "profile": profile}


# ── Decisions ─────────────────────────────────────────────────────────────────


@app.get("/api/decisions")
async def list_decisions(limit: int = 50, _: bool = Depends(verify_api_key)) -> list[dict[str, Any]]:
    """List recorded decisions."""
    decisions = get_decisions(limit=limit)
    return [
        {
            "id": d.id,
            "timestamp": d.timestamp.isoformat(),
            "context": d.context,
            "decision": d.decision,
            "rationale": d.rationale,
            "outcome": d.outcome,
        }
        for d in decisions
    ]


# ── Dashboard ─────────────────────────────────────────────────────────────────


@app.get("/", response_class=HTMLResponse)
async def dashboard() -> str:
    """Serve the web dashboard."""
    return DASHBOARD_HTML


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spectre Dashboard</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               background: #0f1117; color: #e1e4e8; padding: 20px; }
        h1 { color: #58a6ff; margin-bottom: 20px; }
        .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); gap: 16px; }
        .card { background: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
        .card h2 { color: #8b949e; font-size: 14px; text-transform: uppercase; margin-bottom: 12px; }
        .metric { font-size: 24px; font-weight: bold; color: #58a6ff; }
        .status-ok { color: #3fb950; }
        .status-warn { color: #d29922; }
        .status-error { color: #f85149; }
        .btn { background: #238636; color: white; border: none; padding: 8px 16px;
               border-radius: 6px; cursor: pointer; font-size: 14px; margin: 4px; }
        .btn:hover { background: #2ea043; }
        .btn-secondary { background: #30363d; }
        .btn-secondary:hover { background: #3d444d; }
        #status-list { list-style: none; }
        #status-list li { padding: 8px 0; border-bottom: 1px solid #21262d; }
        #workflows { margin-top: 16px; }
        pre { background: #0d1117; padding: 12px; border-radius: 6px; overflow-x: auto; font-size: 13px; }
    </style>
</head>
<body>
    <h1>Spectre Dashboard</h1>
    <div class="grid">
        <div class="card">
            <h2>System Status</h2>
            <ul id="status-list"><li>Loading...</li></ul>
        </div>
        <div class="card">
            <h2>Agents</h2>
            <div id="agents">Loading...</div>
        </div>
        <div class="card">
            <h2>Workflows</h2>
            <div id="workflows">Loading...</div>
        </div>
        <div class="card">
            <h2>Actions</h2>
            <button class="btn" onclick="runWorkflow('morning-startup')">Morning Startup</button>
            <button class="btn" onclick="runWorkflow('weekly-maintenance')">Weekly Maintenance</button>
            <button class="btn" onclick="runWorkflow('security-audit')">Security Audit</button>
            <button class="btn" onclick="runWorkflow('container-cleanup')">Container Cleanup</button>
            <button class="btn btn-secondary" onclick="runWorkflow('model-cleanup')">Model Cleanup</button>
            <button class="btn btn-secondary" onclick="runWorkflow('monthly-optimization')">Monthly Optimize</button>
            <div id="workflow-result" style="margin-top: 12px;"><pre>No workflow run yet.</pre></div>
        </div>
    </div>

    <script>
        async function loadStatus() {
            try {
                const res = await fetch('/api/system/status');
                const data = await res.json();
                const list = document.getElementById('status-list');
                list.innerHTML = '';
                for (const [name, info] of Object.entries(data)) {
                    const li = document.createElement('li');
                    li.innerHTML = '<strong>' + name + '</strong>: ' + JSON.stringify(info).substring(0, 120);
                    list.appendChild(li);
                }
            } catch(e) {
                document.getElementById('status-list').innerHTML = '<li>Error loading status</li>';  # noqa: E501
            }
        }

        async function loadAgents() {
            try {
                const res = await fetch('/api/agents');
                const data = await res.json();
                const spanStyle = 'display:inline-block;background:#30363d;'
                    + 'padding:4px 10px;border-radius:12px;margin:2px;font-size:13px;';
                const agentsHtml = data.agents.map(a => `<span style="${spanStyle}">${a}</span>`).join('');
                document.getElementById('agents').innerHTML = agentsHtml;
            } catch(e) {
                document.getElementById('agents').innerHTML = 'Error loading agents';  # noqa: E501
            }
        }

        async function loadWorkflows() {
            try {
                const res = await fetch('/api/workflows');
                const data = await res.json();
                const spanStyle = 'display:inline-block;background:#30363d;'
                    + 'padding:4px 10px;border-radius:12px;margin:2px;font-size:13px;';
                const workflowsHtml = data.workflows.map(w => `<span style="${spanStyle}">${w}</span>`).join('');
                document.getElementById('workflows').innerHTML = workflowsHtml;
            } catch(e) {
                document.getElementById('workflows').innerHTML = 'Error loading workflows';
            }
        }

        async function runWorkflow(name) {
            const el = document.getElementById('workflow-result');
            el.innerHTML = '<pre>Running ' + name + '...</pre>';
            try {
                const res = await fetch('/api/workflows/' + name, { method: 'POST' });
                const data = await res.json();
                el.innerHTML = '<pre>' + JSON.stringify(data, null, 2) + '</pre>';
            } catch(e) {
                el.innerHTML = '<pre>Error: ' + e.message + '</pre>';
            }
        }

        loadStatus(); loadAgents(); loadWorkflows();
        setInterval(loadStatus, 30000);
    </script>
</body>
</html>"""
