"""Registered effect execution for the store-driven TUI runtime."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
import re

from scholar_outbound_manager.tui.backend import TuiBackendProtocol
from scholar_outbound_manager.tui.effects import CreateSnapshot
from scholar_outbound_manager.tui.effects import Effect
from scholar_outbound_manager.tui.effects import LoadArtifacts
from scholar_outbound_manager.tui.effects import RunAction
from scholar_outbound_manager.tui.effects import RunFetch
from scholar_outbound_manager.tui.effects import RunPortCheck
from scholar_outbound_manager.tui.effects import RunProbe
from scholar_outbound_manager.tui.effects import SaveRouteDraft
from scholar_outbound_manager.tui.events import ActionCompleted
from scholar_outbound_manager.tui.events import AppEvent
from scholar_outbound_manager.tui.events import ArtifactLoaded
from scholar_outbound_manager.tui.events import EffectFailed
from scholar_outbound_manager.tui.events import PortCheckCompleted
from scholar_outbound_manager.tui.view_model import redact_text


class UnsupportedEffectError(RuntimeError):
    """Raised when an effect has no registered handler."""


class EffectRunner:
    """Execute registered effects and convert failures into safe events."""

    def __init__(self, backend: TuiBackendProtocol) -> None:
        self._backend = backend
        self._handlers: dict[type[object], Callable[[object], list[AppEvent]]] = {
            CreateSnapshot: self._handle_create_snapshot,
            RunFetch: self._handle_run_fetch,
            RunProbe: self._handle_run_probe,
            SaveRouteDraft: self._handle_save_route_draft,
            RunPortCheck: self._handle_run_port_check,
            LoadArtifacts: self._handle_load_artifacts,
            RunAction: self._handle_run_action,
        }

    def run_many(self, effects: Sequence[Effect]) -> list[AppEvent]:
        events: list[AppEvent] = []
        for effect in effects:
            events.extend(self.run_one(effect))
        return events

    def run_one(self, effect: object) -> list[AppEvent]:
        handler = self._handlers.get(type(effect))
        if handler is None:
            return [EffectFailed(effect_name=type(effect).__name__, message="Unsupported TUI effect.")]
        try:
            return handler(effect)
        except Exception as exc:
            return [EffectFailed(effect_name=type(effect).__name__, message=_redact_effect_error(exc))]

    def registered_effect_types(self) -> set[type[object]]:
        return set(self._handlers)

    def _handle_create_snapshot(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, CreateSnapshot)
        self._backend.create_snapshot(effect.reason)
        return []

    def _handle_run_fetch(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, RunFetch)
        self._backend.start_fetch()
        return []

    def _handle_run_probe(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, RunProbe)
        self._backend.start_probe()
        return []

    def _handle_save_route_draft(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, SaveRouteDraft)
        self._backend.save_route_draft(effect.entries)
        return [ActionCompleted(action_key="save_route_draft", message="Route draft saved.")]

    def _handle_run_port_check(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, RunPortCheck)
        result = self._backend.run_port_check(effect.route_id)
        return [PortCheckCompleted(route_id=effect.route_id, result=result)]

    def _handle_load_artifacts(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, LoadArtifacts)
        return [ArtifactLoaded(state=self._backend.reload_app_state())]

    def _handle_run_action(self, effect: object) -> list[AppEvent]:
        assert isinstance(effect, RunAction)
        message = self._backend.run_action(effect.action_key)
        return [ActionCompleted(action_key=effect.action_key, message=message)]


def _redact_effect_error(exc: Exception) -> str:
    message = redact_text(str(exc)) or "TUI effect failed."
    return re.sub(r"\b(AppState|CandidateTestRow|RouteStoreState|RouteCandidateOption)\([^)]*\)", "<redacted runtime state>", message)
