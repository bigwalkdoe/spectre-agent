from __future__ import annotations

import json
from http.server import HTTPServer
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import urlopen

import spectre.state as state_mod
from spectre.dashboard import _Handler as DashboardHandler
from spectre.models import Deployment, DeploymentStatus
from spectre.state import save_state


def _serve_in_thread(host: str, port: int, state_dir: Path) -> HTTPServer:
    state_mod._STATE_DIR = state_dir
    server = HTTPServer((host, port), DashboardHandler)
    t = Thread(target=server.serve_forever, daemon=True)
    t.start()
    return server


def test_dashboard_api_returns_deployments(tmp_path: Path) -> None:
    original = state_mod._STATE_DIR
    try:
        state_dir = tmp_path / ".spectre"
        state_mod._STATE_DIR = state_dir
        state_dir.mkdir()
        d = Deployment(
            service="api", environment="staging", version="v1",
            status=DeploymentStatus.healthy,
        )
        save_state([d])

        server = _serve_in_thread("127.0.0.1", 0, state_dir)
        port = server.server_address[1]

        try:
            resp = urlopen(f"http://127.0.0.1:{port}/api/deployments")
            data = json.loads(resp.read())
            assert len(data) == 1
            assert data[0]["service"] == "api"
            assert data[0]["status"] == "healthy"
        finally:
            server.shutdown()
    finally:
        state_mod._STATE_DIR = original


def test_dashboard_root_returns_html(tmp_path: Path) -> None:
    original = state_mod._STATE_DIR
    try:
        state_dir = tmp_path / ".spectre"
        state_mod._STATE_DIR = state_dir
        state_dir.mkdir()

        server = _serve_in_thread("127.0.0.1", 0, state_dir)
        port = server.server_address[1]

        try:
            resp = urlopen(f"http://127.0.0.1:{port}/")
            html = resp.read().decode()
            assert "Spectre Dashboard" in html
        finally:
            server.shutdown()
    finally:
        state_mod._STATE_DIR = original


def test_dashboard_404(tmp_path: Path) -> None:
    original = state_mod._STATE_DIR
    try:
        state_dir = tmp_path / ".spectre"
        state_mod._STATE_DIR = state_dir
        state_dir.mkdir()

        server = _serve_in_thread("127.0.0.1", 0, state_dir)
        port = server.server_address[1]

        try:
            urlopen(f"http://127.0.0.1:{port}/nonexistent")
        except HTTPError as e:
            assert e.code == 404
        finally:
            server.shutdown()
    finally:
        state_mod._STATE_DIR = original
