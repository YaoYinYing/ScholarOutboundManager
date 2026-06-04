from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths
from scholar_outbound_manager.tui.route_draft_store import load_route_draft_entries
from scholar_outbound_manager.tui.route_draft_store import save_route_draft_entries
from scholar_outbound_manager.tui.route_model import RouteEntryDraft


def test_route_draft_store_persists_entries(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text("user_data_dir: state_data\n", encoding="utf-8")
    paths = resolve_user_data_paths(config_path)

    save_route_draft_entries(
        [
            RouteEntryDraft(
                route_id="route-1",
                name="Scholar",
                enabled=True,
                candidate_id="candidate-001",
                candidate_label="US Relay",
                region_hint="US",
                protocol="vless",
                listen_host="127.0.0.1",
                listen_port=19080,
                port_status="free",
                validation_status="ready",
                error=None,
            )
        ],
        paths,
    )

    entries = load_route_draft_entries(paths)

    assert entries[0]["candidate_id"] == "candidate-001"
    assert entries[0]["candidate_label"] == "US Relay"
