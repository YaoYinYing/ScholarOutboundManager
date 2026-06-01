"""Tests for the optional TUI CLI entry points."""

from __future__ import annotations

import builtins
import json
from pathlib import Path

from scholar_outbound_manager import cli
from scholar_outbound_manager.tui import app as tui_app


def test_cli_tui_missing_textual_gives_install_hint(tmp_path: Path, capsys, monkeypatch) -> None:
    """Return a clear install hint when Textual is missing."""
    candidates_path = _write_passed_candidates(tmp_path)
    original_import = builtins.__import__

    def fake_import(name, globals=None, locals=None, fromlist=(), level=0):
        if name.startswith("textual"):
            raise ModuleNotFoundError("No module named 'textual'", name="textual")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    exit_code = cli.main(["tui", "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert 'pip install "ScholarOutboundManager[tui]"' in captured.out or 'pip install "ScholarOutboundManager[tui]"' in captured.err


def test_tui_app_save_selection_writes_artifact(tmp_path: Path) -> None:
    """Save selection through the existing selected-candidate helper."""
    candidates_path = _write_passed_candidates(tmp_path)
    output_path = tmp_path / "selected_candidate.json"

    artifact = tui_app.save_selection_from_index(
        candidates_path=candidates_path,
        selected_index=0,
        output_path=output_path,
    )

    saved = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["selected_candidate_id"] == "candidate-001"
    assert saved["selected_candidate_id"] == "candidate-001"


def test_tui_dashboard_state_is_redacted(tmp_path: Path) -> None:
    """Build a redacted dashboard state without Textual."""
    candidates_path = _write_passed_candidates(tmp_path)

    state = tui_app.load_dashboard_state(
        candidates_path=candidates_path,
        output_path=tmp_path / "selected_candidate.json",
    )

    rendered = json.dumps(state, ensure_ascii=False, sort_keys=True)
    assert state["selected_candidate_id"] == "candidate-001"
    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered


def test_tui_load_workflow_state_contains_tabs_and_wizard(tmp_path: Path) -> None:
    """Build the workflow-oriented state model without Textual."""
    candidates_path = _write_passed_candidates(tmp_path)

    state = tui_app.load_workflow_state(
        candidates_path=str(candidates_path),
        passed_candidates_path=str(candidates_path),
        probe_summary_path=str(tmp_path / "probe_summary.json"),
        selected_candidate_path=str(tmp_path / "selected_candidate.json"),
        session_path=str(tmp_path / "tui_session.json"),
    )

    assert state["tabs"][0] == "Dashboard"
    assert state["wizard_steps"][0]["key"] == "preflight"
    assert state["selection"]["sensitive_notice"].startswith("selected_candidate.json is sensitive")


def test_tui_session_state_does_not_store_sensitive_fields(tmp_path: Path) -> None:
    """Persist only non-sensitive TUI session state."""
    from scholar_outbound_manager.tui.state import build_session_state
    from scholar_outbound_manager.tui.state import write_session_state

    session_path = tmp_path / "tui_session.json"
    state = build_session_state(
        updated_at="2026-06-01T00:00:00Z",
        workspace="/tmp/workspace",
        last_step="probe",
        paths={"config": "config.yaml"},
        last_results={
            "probe": {
                "ok": True,
                "candidate_count": 3,
                "raw_uri": "vless://secret@example.invalid",
                "password": "PASSWORD_PLACEHOLDER",
            }
        },
    )

    write_session_state(session_path, state)
    rendered = session_path.read_text(encoding="utf-8")
    assert "vless://" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "passed_candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "security": "reality",
                            "server_name": "www.cloudflare.com",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    return path
