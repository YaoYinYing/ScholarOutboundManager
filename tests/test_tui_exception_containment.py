from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.effects import RunFetch
from scholar_outbound_manager.tui.backend import CallbackBackend
from scholar_outbound_manager.tui.effect_runner import EffectRunner


def test_effect_runner_exception_is_redacted() -> None:
    runner = EffectRunner(
        CallbackBackend(
            create_snapshot=lambda reason: None,
            start_fetch=lambda: (_ for _ in ()).throw(
                RuntimeError(
                    "AppState(nav='x') vless://fake uuid=00000000-0000-0000-0000-000000000000 "
                    "password=secret server_name=fake.example host=fake.example path=/secret"
                )
            ),
            start_probe=lambda: None,
            save_route_draft=lambda entries: None,
            run_port_check=lambda route_id: (_ for _ in ()).throw(RuntimeError("unused")),
            run_action=lambda action_key: "ok",
            reload_app_state=lambda: (_ for _ in ()).throw(RuntimeError("unused")),
        )
    )

    event = runner.run_one(RunFetch())[0]

    assert "vless://" not in event.message
    assert "00000000-0000-0000-0000-000000000000" not in event.message
    assert "fake.example" not in event.message
    assert "/secret" not in event.message
    assert "AppState(" not in event.message


def test_render_exception_is_caught_and_redacted(tmp_path: Path) -> None:
    captured: list[tuple[str, str]] = []

    def refresh() -> None:
        raise RuntimeError(
            "RouteStoreState(entries=[]) CandidateTestRow(index=1) "
            "vless://fake 00000000-0000-0000-0000-000000000000 password=secret "
            "server_name=fake.example host=fake.example path=/secret"
        )

    succeeded, safe_message = tui_app._run_safe_refresh(
        reason="render",
        refresh_func=refresh,
        render_error=lambda title, message: captured.append((title, message)),
        journal_path=tmp_path / "action_journal.jsonl",
    )

    assert succeeded is False
    assert safe_message is not None
    assert "vless://" not in safe_message
    assert "00000000-0000-0000-0000-000000000000" not in safe_message
    assert "fake.example" not in safe_message
    assert "AppState(" not in safe_message
    assert "CandidateTestRow(" not in safe_message
    assert "RouteStoreState(" not in safe_message


def test_dispatch_event_has_exception_containment_by_source() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    assert 'self._contain_runtime_exception("TUI event dispatch failed", exc)' in source
    assert "raise" not in source[source.index("def dispatch_event"):source.index("def _build_effect_runner")]
