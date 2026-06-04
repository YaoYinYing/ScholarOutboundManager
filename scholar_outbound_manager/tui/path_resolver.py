"""Config-centered path resolution for the TUI."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_USER_DATA_DIR = "state_data"


@dataclass(slots=True, frozen=True)
class UserDataPaths:
    """Resolved user-data artifact paths derived from one config path."""

    config_path: Path
    root: Path
    candidates: Path
    probe_summary: Path
    passed_candidates: Path
    selected_candidate: Path
    selected_routes: Path
    pool_plan: Path
    action_journal: Path
    undo_journal: Path
    snapshot_root: Path
    session: Path
    geo_cache: Path
    host_geo: Path


def resolve_user_data_paths(
    config_path: str | Path,
    *,
    user_data_dir: str | Path | None = None,
) -> UserDataPaths:
    """Resolve artifact paths from the config-local user-data root."""
    config_file = Path(config_path)
    config_dir = config_file.parent if str(config_file.parent) else Path(".")
    configured_root = Path(user_data_dir) if user_data_dir is not None else Path(read_user_data_dir(config_file))
    root = configured_root if configured_root.is_absolute() else (config_dir / configured_root)
    tui_root = root / "tui"
    geo_root = root / "geo"
    return UserDataPaths(
        config_path=config_file,
        root=root,
        candidates=root / "candidates.json",
        probe_summary=root / "probe_summary.json",
        passed_candidates=root / "passed_candidates.json",
        selected_candidate=root / "selected_candidate.json",
        selected_routes=root / "selected_routes.json",
        pool_plan=root / "sidecar_pool_plan.json",
        action_journal=tui_root / "action_journal.jsonl",
        undo_journal=tui_root / "config_undo_journal.jsonl",
        snapshot_root=tui_root / "artifact_snapshots",
        session=root / "tui_session.json",
        geo_cache=geo_root / "candidate_geo_cache.json",
        host_geo=geo_root / "host_geo.json",
    )


def read_user_data_dir(config_path: str | Path, *, default: str = DEFAULT_USER_DATA_DIR) -> str:
    """Read the configured user_data_dir from raw YAML without requiring a valid full config."""
    raw = _load_raw_mapping(config_path)
    value = raw.get("user_data_dir")
    return str(value) if isinstance(value, str) and value.strip() else default


def load_raw_config_mapping(config_path: str | Path) -> dict[str, Any]:
    """Return one raw config mapping or an empty mapping if unavailable."""
    return _load_raw_mapping(config_path)


def _load_raw_mapping(config_path: str | Path) -> dict[str, Any]:
    config_file = Path(config_path)
    if not config_file.exists():
        return {}
    try:
        payload = yaml.safe_load(config_file.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return dict(payload) if isinstance(payload, dict) else {}
