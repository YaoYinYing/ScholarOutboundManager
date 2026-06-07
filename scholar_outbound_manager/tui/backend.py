"""Backend protocol and callback adapter for the store-driven TUI runtime."""

from __future__ import annotations

from collections.abc import Callable
from collections.abc import Sequence
from typing import Protocol

from scholar_outbound_manager.tui.port_check import PortCheckResult
from scholar_outbound_manager.tui.route_model import RouteEntryDraft
from scholar_outbound_manager.tui.state import AppState


class TuiBackendProtocol(Protocol):
    def create_snapshot(self, reason: str) -> None: ...
    def start_fetch(self) -> None: ...
    def start_probe(self) -> None: ...
    def save_route_draft(self, entries: Sequence[RouteEntryDraft]) -> None: ...
    def run_port_check(self, route_id: str) -> PortCheckResult: ...
    def run_action(self, action_key: str) -> str: ...
    def reload_app_state(self) -> AppState: ...


class CallbackBackend:
    """Small callback-backed backend adapter used by the Textual app."""

    def __init__(
        self,
        *,
        create_snapshot: Callable[[str], None],
        start_fetch: Callable[[], None],
        start_probe: Callable[[], None],
        save_route_draft: Callable[[Sequence[RouteEntryDraft]], None],
        run_port_check: Callable[[str], PortCheckResult],
        run_action: Callable[[str], str],
        reload_app_state: Callable[[], AppState],
    ) -> None:
        self._create_snapshot = create_snapshot
        self._start_fetch = start_fetch
        self._start_probe = start_probe
        self._save_route_draft = save_route_draft
        self._run_port_check = run_port_check
        self._run_action = run_action
        self._reload_app_state = reload_app_state

    def create_snapshot(self, reason: str) -> None:
        self._create_snapshot(reason)

    def start_fetch(self) -> None:
        self._start_fetch()

    def start_probe(self) -> None:
        self._start_probe()

    def save_route_draft(self, entries: Sequence[RouteEntryDraft]) -> None:
        self._save_route_draft(entries)

    def run_port_check(self, route_id: str) -> PortCheckResult:
        return self._run_port_check(route_id)

    def run_action(self, action_key: str) -> str:
        return self._run_action(action_key)

    def reload_app_state(self) -> AppState:
        return self._reload_app_state()

