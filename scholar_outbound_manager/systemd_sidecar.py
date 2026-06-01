"""Production systemd helpers for the Scholar SOCKS sidecar."""

from __future__ import annotations

import os
import re
import shutil
import subprocess
import hashlib
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path
from typing import Callable

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import XrayConfig
from scholar_outbound_manager.selection import extract_candidate_selection_records
from scholar_outbound_manager.sidecar_pool import build_multi_port_sidecar_runtime_config
from scholar_outbound_manager.sidecar_pool import SidecarPoolPlan
from scholar_outbound_manager.sidecar_pool import check_pool_ports_available
from scholar_outbound_manager.sidecar_pool import pool_plan_to_dict
from scholar_outbound_manager.sidecar import build_socks_outbound_snippet
from scholar_outbound_manager.state.atomic_write import atomic_write_json
from scholar_outbound_manager.xray.outbound import build_xray_outbound
from scholar_outbound_manager.xray.runtime_config import build_runtime_config_from_outbound
from scholar_outbound_manager.xray.runtime_config import write_runtime_config


@dataclass(slots=True)
class SystemdSidecarOptions:
    """Define production sidecar staging and systemd service options."""

    unit_name: str = "scholar-outbound-sidecar.service"
    service_user: str = "scholar-sidecar"
    service_group: str = "scholar-sidecar"
    install_root: str = "/opt/scholar-outbound-manager"
    config_dir: str = "/etc/scholar-outbound-manager"
    state_dir: str = "/var/lib/scholar-outbound-manager"
    runtime_config_name: str = "scholar_sidecar_runtime.json"
    xray_binary_name: str = "xray"
    listen_host: str = "127.0.0.1"
    listen_port: int = 19080
    restart_policy: str = "on-failure"
    restart_sec: int = 5


@dataclass(slots=True)
class SystemdSidecarPaths:
    """Collect production file-system paths for the systemd sidecar."""

    unit_path: str
    xray_binary_path: str
    runtime_config_path: str
    state_dir: str
    metadata_path: str


@dataclass(slots=True)
class SystemdCommandResult:
    """Represent one executed system command for systemd-sidecar setup."""

    command: list[str]
    returncode: int
    stdout: str
    stderr: str
    ok: bool


def all_command_results_ok(results: list[SystemdCommandResult]) -> bool:
    """Return True only when every system command result succeeded."""
    return all(result.ok for result in results)


def summarize_command_results(results: list[SystemdCommandResult]) -> tuple[bool, list[str]]:
    """Summarize command failures without echoing full subprocess output."""
    failures = [result for result in results if not result.ok]
    if not failures:
        return True, []
    messages = [
        f"{' '.join(result.command[:3])}: returncode={result.returncode}"
        for result in failures
    ]
    return False, messages


def system_user_preparation_ok(results: list[SystemdCommandResult]) -> bool:
    """Return True when system user/group checks either pass or recover via create commands."""
    command_map = {tuple(result.command): result for result in results}
    group_check = next((result for result in results if result.command[:2] == ["getent", "group"]), None)
    user_check = next((result for result in results if result.command[:2] == ["id", "-u"]), None)

    group_ok = group_check is not None and (
        group_check.ok
        or command_map.get(("groupadd", "--system", group_check.command[-1])) is not None
        and command_map[("groupadd", "--system", group_check.command[-1])].ok
    )
    user_ok = user_check is not None and (
        user_check.ok
        or any(
            result.command[:2] == ["useradd", "--system"] and result.ok
            for result in results
        )
    )
    return group_ok and user_ok


def summarize_system_user_results(results: list[SystemdCommandResult]) -> tuple[bool, list[str]]:
    """Summarize only unrecovered user/group preparation failures."""
    if system_user_preparation_ok(results):
        return True, []
    relevant = [
        result
        for result in results
        if result.command[:2] in (["getent", "group"], ["groupadd", "--system"], ["id", "-u"], ["useradd", "--system"])
        and not result.ok
    ]
    return summarize_command_results(relevant)


def validate_systemd_unit_name(unit_name: str) -> None:
    """Validate one systemd unit file name."""
    if not unit_name:
        raise ValueError("unit_name must not be empty.")
    if not unit_name.endswith(".service"):
        raise ValueError("unit_name must end with .service.")
    if "/" in unit_name or "\\" in unit_name or ".." in unit_name:
        raise ValueError("unit_name must not contain path separators or '..'.")
    if re.fullmatch(r"[A-Za-z0-9_.@-]+", unit_name) is None:
        raise ValueError("unit_name contains unsupported characters.")


def validate_system_user_name(name: str) -> None:
    """Validate one dedicated Linux system user or group name."""
    if not name:
        raise ValueError("system user name must not be empty.")
    if name == "root":
        raise ValueError("root is not allowed for production sidecar helpers.")
    if any(char in name for char in ("/", "\\", " ", ":")):
        raise ValueError("system user name contains unsupported characters.")
    if re.fullmatch(r"[a-z0-9_-]+", name) is None:
        raise ValueError("system user name contains unsupported characters.")


def build_systemd_sidecar_paths(options: SystemdSidecarOptions) -> SystemdSidecarPaths:
    """Build production file-system paths without creating files."""
    validate_systemd_unit_name(options.unit_name)
    validate_system_user_name(options.service_user)
    validate_system_user_name(options.service_group)
    _validate_plain_file_name(options.runtime_config_name, "runtime_config_name")
    _validate_plain_file_name(options.xray_binary_name, "xray_binary_name")
    _validate_listen_options(options.listen_host, options.listen_port)
    _validate_positive_int(options.restart_sec, "restart_sec")

    install_root = Path(options.install_root)
    config_dir = Path(options.config_dir)
    state_dir = Path(options.state_dir)
    return SystemdSidecarPaths(
        unit_path=str(Path("/etc/systemd/system") / options.unit_name),
        xray_binary_path=str(install_root / "xray" / options.xray_binary_name),
        runtime_config_path=str(config_dir / options.runtime_config_name),
        state_dir=str(state_dir),
        metadata_path=str(state_dir / "scholar_sidecar.metadata.json"),
    )


def render_sidecar_systemd_unit(
    options: SystemdSidecarOptions,
    paths: SystemdSidecarPaths,
) -> str:
    """Render one production systemd unit without embedding credentials."""
    validate_systemd_unit_name(options.unit_name)
    validate_system_user_name(options.service_user)
    validate_system_user_name(options.service_group)
    _validate_plain_file_name(options.runtime_config_name, "runtime_config_name")
    _validate_restart_policy(options.restart_policy)
    _validate_positive_int(options.restart_sec, "restart_sec")

    return (
        "[Unit]\n"
        "Description=ScholarOutboundManager Xray sidecar\n"
        "After=network-online.target\n"
        "Wants=network-online.target\n"
        "\n"
        "[Service]\n"
        "Type=simple\n"
        f"User={options.service_user}\n"
        f"Group={options.service_group}\n"
        f"ExecStart={paths.xray_binary_path} run -config {paths.runtime_config_path}\n"
        f"Restart={options.restart_policy}\n"
        f"RestartSec={options.restart_sec}\n"
        "KillSignal=SIGTERM\n"
        "TimeoutStopSec=10\n"
        "NoNewPrivileges=true\n"
        "PrivateTmp=true\n"
        "ProtectSystem=full\n"
        "ProtectHome=true\n"
        f"ReadWritePaths={paths.state_dir} /run/scholar-outbound-manager\n"
        "RuntimeDirectory=scholar-outbound-manager\n"
        "StateDirectory=scholar-outbound-manager\n"
        "\n"
        "[Install]\n"
        "WantedBy=multi-user.target\n"
    )


def render_socks_outbound_snippet_for_sidecar(
    listen_host: str,
    listen_port: int,
    tag: str = "scholar-sidecar-socks-out",
) -> dict[str, object]:
    """Return one production-reference SOCKS outbound snippet."""
    return build_socks_outbound_snippet(listen_host, listen_port, tag)


def stage_systemd_sidecar_files(
    *,
    candidate: CandidateProxy,
    candidate_id: str | None,
    xray_config: XrayConfig,
    options: SystemdSidecarOptions,
    source_xray_binary_path: str | Path | None = None,
    skip_xray_binary_copy: bool = False,
    file_ops: object | None = None,
) -> SystemdSidecarPaths:
    """Stage production sidecar files without starting systemd or Xray."""
    paths = build_systemd_sidecar_paths(options)
    source_binary_path = Path(
        xray_config.binary_path if source_xray_binary_path is None else source_xray_binary_path
    )
    destination_binary_path = Path(paths.xray_binary_path)
    runtime_config_path = Path(paths.runtime_config_path)
    state_dir = Path(paths.state_dir)
    metadata_path = Path(paths.metadata_path)

    _ops_mkdir(file_ops, destination_binary_path.parent, mode=0o755)
    _ops_mkdir(file_ops, runtime_config_path.parent, mode=0o750)
    _ops_mkdir(file_ops, state_dir, mode=0o750)

    binary_copy_mode = _stage_xray_binary(
        source_binary_path=source_binary_path,
        destination_binary_path=destination_binary_path,
        skip_xray_binary_copy=skip_xray_binary_copy,
        file_ops=file_ops,
    )
    _ops_chmod(file_ops, destination_binary_path, 0o755)
    _ops_chown(file_ops, destination_binary_path, options.service_user, options.service_group)

    outbound = build_xray_outbound(candidate, "scholar-sidecar-out")
    runtime_config = build_runtime_config_from_outbound(
        outbound=outbound,
        listen_host=options.listen_host,
        listen_port=options.listen_port,
        inbound_tag="scholar-sidecar-socks-in",
    )
    write_runtime_config(runtime_config_path, runtime_config)
    _ops_chmod(file_ops, runtime_config_path, 0o600)
    _ops_chown(file_ops, runtime_config_path, options.service_user, options.service_group)

    atomic_write_json(
        metadata_path,
        {
            "schema_version": 1,
            "candidate_id": candidate_id,
            "candidate_protocol": candidate.protocol,
            "listen_host": options.listen_host,
            "listen_port": options.listen_port,
            "xray_binary_path": paths.xray_binary_path,
            "xray_binary_copy_mode": binary_copy_mode,
            "runtime_config_path": paths.runtime_config_path,
            "metadata_path": paths.metadata_path,
            "state_dir": paths.state_dir,
            "prepared_at": _utc_now_iso8601(),
        },
    )
    _ops_chmod(file_ops, metadata_path, 0o640)
    _ops_chown(file_ops, metadata_path, options.service_user, options.service_group)
    _ops_chown(file_ops, state_dir, options.service_user, options.service_group)
    _ops_chown(file_ops, runtime_config_path.parent, options.service_user, options.service_group)

    return paths


def stage_single_xray_pool_files(
    *,
    payload: dict[str, object],
    plan: SidecarPoolPlan,
    xray_config: XrayConfig,
    options: SystemdSidecarOptions,
    source_xray_binary_path: str | Path | None = None,
    skip_xray_binary_copy: bool = False,
    file_ops: object | None = None,
    allow_port_conflict: bool = False,
) -> SystemdSidecarPaths:
    """Stage one single-Xray multi-port pool runtime without installing the unit."""
    paths = build_systemd_sidecar_paths(options)
    paths = SystemdSidecarPaths(
        unit_path=paths.unit_path,
        xray_binary_path=paths.xray_binary_path,
        runtime_config_path=paths.runtime_config_path,
        state_dir=paths.state_dir,
        metadata_path=str(Path(paths.state_dir) / "scholar_sidecar_pool.metadata.json"),
    )
    source_binary_path = Path(
        xray_config.binary_path if source_xray_binary_path is None else source_xray_binary_path
    )
    destination_binary_path = Path(paths.xray_binary_path)
    runtime_config_path = Path(paths.runtime_config_path)
    state_dir = Path(paths.state_dir)
    metadata_path = Path(paths.metadata_path)

    port_availability = check_pool_ports_available(plan)
    unavailable_ports = [entry.listen_port for entry in plan.entries if not port_availability.get(entry.pool_index, False)]
    if unavailable_ports and not allow_port_conflict:
        unavailable_text = ", ".join(str(port) for port in unavailable_ports)
        raise ValueError(
            "Pool listen ports are already in use: "
            f"{unavailable_text}. Stop the running sidecar service first or choose a different base port."
        )

    candidates_by_id = {
        record.candidate_id: record.candidate
        for record in extract_candidate_selection_records(payload)
    }
    runtime_config = build_multi_port_sidecar_runtime_config(
        entries=plan.entries,
        candidates_by_id=candidates_by_id,
    )

    _ops_mkdir(file_ops, destination_binary_path.parent, mode=0o755)
    _ops_mkdir(file_ops, runtime_config_path.parent, mode=0o750)
    _ops_mkdir(file_ops, state_dir, mode=0o750)

    binary_copy_mode = _stage_xray_binary(
        source_binary_path=source_binary_path,
        destination_binary_path=destination_binary_path,
        skip_xray_binary_copy=skip_xray_binary_copy,
        file_ops=file_ops,
    )
    _ops_chmod(file_ops, destination_binary_path, 0o755)
    _ops_chown(file_ops, destination_binary_path, options.service_user, options.service_group)

    write_runtime_config(runtime_config_path, runtime_config)
    _ops_chmod(file_ops, runtime_config_path, 0o600)
    _ops_chown(file_ops, runtime_config_path, options.service_user, options.service_group)

    atomic_write_json(
        metadata_path,
        {
            "schema_version": 1,
            "mode": "single_xray_multi_port",
            "entry_count": plan.count,
            "listen_host": plan.listen_host,
            "base_port": plan.base_port,
            "ports_available": port_availability,
            "xray_binary_path": paths.xray_binary_path,
            "xray_binary_copy_mode": binary_copy_mode,
            "runtime_config_path": paths.runtime_config_path,
            "metadata_path": paths.metadata_path,
            "state_dir": paths.state_dir,
            "plan": pool_plan_to_dict(plan),
            "prepared_at": _utc_now_iso8601(),
        },
    )
    _ops_chmod(file_ops, metadata_path, 0o640)
    _ops_chown(file_ops, metadata_path, options.service_user, options.service_group)
    _ops_chown(file_ops, state_dir, options.service_user, options.service_group)
    _ops_chown(file_ops, runtime_config_path.parent, options.service_user, options.service_group)

    return paths


def build_ensure_system_user_commands(options: SystemdSidecarOptions) -> list[list[str]]:
    """Build the check and create commands for the dedicated system user/group."""
    validate_system_user_name(options.service_user)
    validate_system_user_name(options.service_group)
    return [
        ["getent", "group", options.service_group],
        ["groupadd", "--system", options.service_group],
        ["id", "-u", options.service_user],
        [
            "useradd",
            "--system",
            "--gid",
            options.service_group,
            "--home-dir",
            options.state_dir,
            "--shell",
            "/usr/sbin/nologin",
            options.service_user,
        ],
    ]


def ensure_system_user(
    options: SystemdSidecarOptions,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[SystemdCommandResult]:
    """Ensure the dedicated system group and user exist."""
    commands = build_ensure_system_user_commands(options)
    results: list[SystemdCommandResult] = []

    group_check = _run_command(commands[0], runner)
    results.append(group_check)
    if group_check.returncode != 0:
        results.append(_run_command(commands[1], runner))

    user_check = _run_command(commands[2], runner)
    results.append(user_check)
    if user_check.returncode != 0:
        results.append(_run_command(commands[3], runner))

    return results


def install_systemd_unit(
    unit_text: str,
    unit_path: str | Path,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> list[SystemdCommandResult]:
    """Write one systemd unit file and reload the unit registry."""
    path = Path(unit_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(unit_text, encoding="utf-8")
    os.chmod(path, 0o644)
    return [_run_command(["systemctl", "daemon-reload"], runner)]


def run_systemctl(
    action: str,
    unit_name: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> SystemdCommandResult:
    """Run one allowlisted systemctl action for the configured unit."""
    validate_systemd_unit_name(unit_name)
    if action not in {"start", "stop", "restart", "status", "enable", "disable", "is-active", "is-enabled"}:
        raise ValueError("action is not allowed for run_systemctl.")
    return _run_command(["systemctl", action, unit_name], runner)


def _run_command(
    command: list[str],
    runner: Callable[..., subprocess.CompletedProcess[str]],
) -> SystemdCommandResult:
    """Run one subprocess command and normalize the result."""
    completed = runner(
        command,
        capture_output=True,
        text=True,
        check=False,
    )
    return SystemdCommandResult(
        command=list(command),
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
        ok=completed.returncode == 0,
    )


def _ops_mkdir(file_ops: object | None, path: Path, *, mode: int) -> None:
    """Create one directory through injected file ops when provided."""
    if file_ops is not None and hasattr(file_ops, "mkdir"):
        file_ops.mkdir(path, mode=mode)
        return
    path.mkdir(parents=True, exist_ok=True, mode=mode)


def _ops_copy2(file_ops: object | None, src: Path, dst: Path) -> None:
    """Copy one file through injected file ops when provided."""
    if file_ops is not None and hasattr(file_ops, "copy2"):
        file_ops.copy2(src, dst)
        return
    shutil.copy2(src, dst)


def _ops_chmod(file_ops: object | None, path: Path, mode: int) -> None:
    """Apply chmod through injected file ops when provided."""
    if file_ops is not None and hasattr(file_ops, "chmod"):
        file_ops.chmod(path, mode)
        return
    os.chmod(path, mode)


def _ops_chown(file_ops: object | None, path: Path, user: str, group: str) -> None:
    """Apply chown through injected file ops when provided."""
    if file_ops is not None and hasattr(file_ops, "chown"):
        file_ops.chown(path, user, group)
        return
    shutil.chown(path, user=user, group=group)


def _stage_xray_binary(
    *,
    source_binary_path: Path,
    destination_binary_path: Path,
    skip_xray_binary_copy: bool,
    file_ops: object | None,
) -> str:
    """Stage the Xray binary without overwriting a differing existing target."""
    if skip_xray_binary_copy:
        _require_existing_executable_binary(destination_binary_path)
        return "skipped"
    if source_binary_path.resolve() == destination_binary_path.resolve():
        _require_existing_executable_binary(destination_binary_path)
        return "in_place"
    if destination_binary_path.exists():
        source_hash = _compute_file_sha256(source_binary_path)
        destination_hash = _compute_file_sha256(destination_binary_path)
        if source_hash == destination_hash:
            _require_existing_executable_binary(destination_binary_path)
            return "unchanged"
        raise ValueError(
            "target Xray binary differs; stop service first or use explicit binary upgrade workflow"
        )
    _ops_copy2(file_ops, source_binary_path, destination_binary_path)
    return "copied"


def _require_existing_executable_binary(path: Path) -> None:
    """Require one existing executable Xray binary."""
    if not path.exists():
        raise ValueError("target Xray binary does not exist; cannot skip binary copy.")
    if not path.is_file() or not os.access(path, os.X_OK):
        raise ValueError("target Xray binary is not executable; cannot skip binary copy.")


def _compute_file_sha256(path: Path) -> str:
    """Compute one SHA-256 digest for a local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_plain_file_name(value: str, field_name: str) -> None:
    """Validate one plain file name field."""
    if not value:
        raise ValueError(f"{field_name} must not be empty.")
    if "/" in value or "\\" in value or value in {".", ".."}:
        raise ValueError(f"{field_name} must be a plain file name.")


def _validate_listen_options(listen_host: str, listen_port: int) -> None:
    """Validate systemd sidecar listen settings."""
    if not listen_host:
        raise ValueError("listen_host must not be empty.")
    if listen_port <= 0:
        raise ValueError("listen_port must be greater than 0.")


def _validate_positive_int(value: int, field_name: str) -> None:
    """Validate one positive integer option."""
    if value <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")


def _validate_restart_policy(policy: str) -> None:
    """Validate one systemd restart policy string."""
    if policy not in {"no", "on-success", "on-failure", "on-abnormal", "on-watchdog", "always"}:
        raise ValueError("restart_policy is not supported.")


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
