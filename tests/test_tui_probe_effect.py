from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.tui.control_plane import load_control_plane_state
from scholar_outbound_manager.tui.path_resolver import resolve_user_data_paths


def test_probe_operation_uses_canonical_paths_parallel_and_keep_all_passed(tmp_path: Path) -> None:
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        "user_data_dir: state_data\nprobe:\n  concurrency: 4\nsubscription:\n  url: https://example.invalid/sub\n",
        encoding="utf-8",
    )
    paths = resolve_user_data_paths(config_path)
    state = load_control_plane_state(config_path=str(config_path))

    probe = next(operation for operation in state.command_state.operations if operation.key == "probe")

    assert str(paths.candidates) in probe.command
    assert str(paths.probe_summary) in probe.command
    assert str(paths.passed_candidates) in probe.command
    assert "--parallel" in probe.command
    assert probe.command[probe.command.index("--parallel") + 1] == "4"
    assert "--keep-all-passed" in probe.command
