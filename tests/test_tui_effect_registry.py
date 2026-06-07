from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.tui import app as tui_app
from scholar_outbound_manager.tui.backend import CallbackBackend
from scholar_outbound_manager.tui.effect_runner import EffectRunner
from scholar_outbound_manager.tui.events import EffectFailed
from scholar_outbound_manager.tui import effects as effect_types
from scholar_outbound_manager.tui.port_check import PortCheckResult


def test_all_concrete_effect_classes_are_registered() -> None:
    runner = EffectRunner(_backend())
    registered = runner.registered_effect_types()
    expected = {
        effect_types.CreateSnapshot,
        effect_types.RunFetch,
        effect_types.RunProbe,
        effect_types.SaveRouteDraft,
        effect_types.RunPortCheck,
        effect_types.LoadArtifacts,
        effect_types.RunAction,
    }

    assert expected == registered


def test_unknown_effect_returns_effect_failed_instead_of_raising() -> None:
    runner = EffectRunner(_backend())

    @dataclass(frozen=True)
    class UnknownEffect:
        name: str = "unknown"

    events = runner.run_one(UnknownEffect())

    assert events == [EffectFailed(effect_name="UnknownEffect", message="Unsupported TUI effect.")]


def test_effect_runner_would_catch_missing_handler_chain_bug() -> None:
    source = Path(tui_app.__file__).read_text(encoding="utf-8")

    assert "if isinstance(effect, RunFetch)" not in source
    assert "if isinstance(effect, RunProbe)" not in source
    assert "RunFetch" in Path(effect_types.__file__).read_text(encoding="utf-8")


def _backend() -> CallbackBackend:
    return CallbackBackend(
        create_snapshot=lambda reason: None,
        start_fetch=lambda: None,
        start_probe=lambda: None,
        save_route_draft=lambda entries: None,
        run_port_check=lambda route_id: PortCheckResult(status="free", message="Port is free.", reusable=True, owner_label=None, owner_kind=None),
        run_action=lambda action_key: f"{action_key} completed",
        reload_app_state=lambda: (_ for _ in ()).throw(RuntimeError("reload should not run in this test")),
    )

