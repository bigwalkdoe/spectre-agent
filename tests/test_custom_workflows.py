"""Tests for custom workflow loading and management."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import yaml

from packages.workflow_engine.engine import (
    Step,
    WorkflowDefinition,
    WorkflowEngine,
    _parse_workflow_definition,
    load_workflow_from_json,
    load_workflow_from_yaml,
    load_workflows_from_dir,
)


def test_parse_workflow_definition() -> None:
    data = {
        "name": "test-wf",
        "description": "Test workflow",
        "steps": [
            {"agent": "linux", "action": "system-health-check"},
            {"agent": "security", "action": "ports-audit", "max_retries": 2},
        ],
    }
    wf = _parse_workflow_definition(data)
    assert wf is not None
    assert wf.name == "test-wf"
    assert wf.description == "Test workflow"
    assert len(wf.steps) == 2
    assert wf.steps[0].agent == "linux"
    assert wf.steps[1].max_retries == 2


def test_parse_workflow_definition_invalid() -> None:
    assert _parse_workflow_definition({}) is None
    # Name only (no steps) returns a valid definition with empty steps
    wf = _parse_workflow_definition({"name": "test"})
    assert wf is not None
    assert wf.steps == []


def test_load_workflow_from_yaml() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.yaml"
        data = {
            "name": "yaml-wf",
            "description": "Loaded from YAML",
            "steps": [{"agent": "linux", "action": "system-health-check"}],
        }
        path.write_text(yaml.safe_dump(data))
        wf = load_workflow_from_yaml(path)
        assert wf is not None
        assert wf.name == "yaml-wf"
        assert len(wf.steps) == 1


def test_load_workflow_from_yaml_not_found() -> None:
    assert load_workflow_from_yaml("/nonexistent/path.yaml") is None


def test_load_workflow_from_json() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.json"
        data = {
            "name": "json-wf",
            "description": "Loaded from JSON",
            "steps": [{"agent": "devops", "action": "podman-prune"}],
        }
        path.write_text(json.dumps(data))
        wf = load_workflow_from_json(path)
        assert wf is not None
        assert wf.name == "json-wf"
        assert len(wf.steps) == 1


def test_load_workflow_from_json_not_found() -> None:
    assert load_workflow_from_json("/nonexistent/path.json") is None


def test_load_workflows_from_dir() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        # YAML workflow
        yaml_data = {
            "name": "yaml-wf",
            "description": "YAML workflow",
            "steps": [{"agent": "linux", "action": "system-health-check"}],
        }
        Path(tmpdir) / "test.yaml"
        (Path(tmpdir) / "test.yaml").write_text(yaml.safe_dump(yaml_data))

        # JSON workflow
        json_data = {
            "name": "json-wf",
            "description": "JSON workflow",
            "steps": [{"agent": "devops", "action": "podman-prune"}],
        }
        (Path(tmpdir) / "test.json").write_text(json.dumps(json_data))

        workflows = load_workflows_from_dir(tmpdir)
        assert len(workflows) == 2
        assert "yaml-wf" in workflows
        assert "json-wf" in workflows


def test_load_workflows_from_dir_not_found() -> None:
    assert load_workflows_from_dir("/nonexistent/dir") == {}


def test_engine_load_workflows() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data = {
            "name": "custom-wf",
            "description": "Custom workflow",
            "steps": [{"agent": "linux", "action": "system-health-check"}],
        }
        (Path(tmpdir) / "custom.yaml").write_text(yaml.safe_dump(data))

        engine = WorkflowEngine()
        count = engine.load_workflows(tmpdir)
        assert count == 1
        assert "custom-wf" in engine.get_available_workflows()
        assert "custom-wf" in engine.custom_workflows


def test_engine_register_workflow() -> None:
    engine = WorkflowEngine()
    wf = WorkflowDefinition(
        name="runtime-wf",
        description="Registered at runtime",
        steps=[Step(agent="linux", action="system-health-check")],
    )
    engine.register_workflow(wf)
    assert "runtime-wf" in engine.get_available_workflows()
    assert engine.custom_workflows["runtime-wf"] is wf


def test_engine_get_workflow_definitions_includes_custom() -> None:
    engine = WorkflowEngine()
    wf = WorkflowDefinition(
        name="my-custom",
        description="Custom",
        steps=[Step(agent="linux", action="system-health-check")],
    )
    engine.register_workflow(wf)
    defs = engine.get_workflow_definitions()
    assert "my-custom" in defs
    assert "morning-startup" in defs  # built-in still there


def test_engine_run_custom_workflow() -> None:
    engine = WorkflowEngine()
    wf = WorkflowDefinition(
        name="test-run",
        description="Test",
        steps=[Step(agent="linux", action="system-health-check")],
    )
    engine.register_workflow(wf)
    result = engine.run_workflow("test-run")
    assert result["workflow"] == "test-run"
    assert result["status"] in ("success", "failed")


def test_engine_workflows_dir_constructor() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        data = {
            "name": "init-wf",
            "description": "Init workflow",
            "steps": [{"agent": "linux", "action": "system-health-check"}],
        }
        (Path(tmpdir) / "init.yaml").write_text(yaml.safe_dump(data))

        engine = WorkflowEngine(workflows_dir=tmpdir)
        assert "init-wf" in engine.get_available_workflows()


def test_custom_workflow_with_events() -> None:
    engine = WorkflowEngine()
    wf = WorkflowDefinition(
        name="event-wf",
        description="With events",
        steps=[
            Step(
                agent="linux",
                action="system-health-check",
                on_success="step.success",
                on_failure="step.failure",
            ),
        ],
        on_complete="workflow.done",
    )
    engine.register_workflow(wf)
    result = engine.run_workflow("event-wf")
    assert result["workflow"] == "event-wf"
