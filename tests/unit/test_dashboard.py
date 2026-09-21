"""Unit tests for the Resync review dashboard and REST APIs."""

from __future__ import annotations

from pathlib import Path

from mcp.server.mcpserver import MCPServer
from starlette.testclient import TestClient

from resync.server.dashboard import (
    apply_dashboard_decision,
    attach_dashboard,
    get_dashboard_decisions,
    get_dashboard_status,
    render_dashboard_html,
)


def test_get_dashboard_status(tmp_path: Path) -> None:
    status = get_dashboard_status(tmp_path)
    assert "repo_root" in status
    assert "mode" in status
    assert "tools" in status
    assert "kpis" in status
    kpis = status["kpis"]
    assert "breakages_detected" in kpis
    assert "trust_score" in kpis


def test_get_dashboard_decisions_empty(tmp_path: Path) -> None:
    decisions = get_dashboard_decisions(tmp_path)
    assert isinstance(decisions, list)


def test_apply_dashboard_decision_pin_and_exception(tmp_path: Path) -> None:
    pin_res = apply_dashboard_decision(tmp_path, {"action": "pin", "target": "transformers.pipeline"})
    assert pin_res["success"] is True

    config_content = (tmp_path / "resync.toml").read_text(encoding="utf-8")
    assert "transformers.pipeline" in config_content
    assert "[[pin]]" in config_content

    exc_res = apply_dashboard_decision(tmp_path, {"action": "exception", "target": "requests.get"})
    assert exc_res["success"] is True
    config_content = (tmp_path / "resync.toml").read_text(encoding="utf-8")
    assert "requests.get" in config_content
    assert "[[exception]]" in config_content


def test_apply_dashboard_decision_invalid(tmp_path: Path) -> None:
    res = apply_dashboard_decision(tmp_path, {})
    assert res["success"] is False


def test_render_dashboard_html(tmp_path: Path) -> None:
    html = render_dashboard_html(tmp_path)
    assert "<!DOCTYPE html>" in html
    assert "Resync Engine" in html
    assert "#0b0f19" in html
    assert "JetBrains Mono" in html
    assert "Pending Compatibility Decisions" in html


def test_dashboard_routes_integration(tmp_path: Path) -> None:
    server = MCPServer(name="resync-test", version="0.1.0")
    attach_dashboard(server, tmp_path)

    app = server.streamable_http_app(stateless_http=True)
    client = TestClient(app)

    # Root redirect
    resp_root = client.get("/", follow_redirects=False)
    assert resp_root.status_code == 307
    assert resp_root.headers["location"] == "/dashboard"

    # Dashboard UI
    resp_ui = client.get("/dashboard")
    assert resp_ui.status_code == 200
    assert "Resync Engine" in resp_ui.text

    # Status API
    resp_status = client.get("/api/dashboard/status")
    assert resp_status.status_code == 200
    data = resp_status.json()
    assert "kpis" in data

    # Decisions API
    resp_decisions = client.get("/api/dashboard/decisions")
    assert resp_decisions.status_code == 200
    assert isinstance(resp_decisions.json(), list)

    # Apply Decision API
    resp_apply = client.post("/api/dashboard/decisions/apply", json={"action": "pin", "target": "my.symbol"})
    assert resp_apply.status_code == 200
    assert resp_apply.json()["success"] is True
