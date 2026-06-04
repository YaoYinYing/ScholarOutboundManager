"""Structured allowlisted config form helpers for the TUI control plane."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.tui.config_editor import build_redacted_config_diff
from scholar_outbound_manager.tui.config_editor import load_config_draft
from scholar_outbound_manager.tui.config_editor import redact_validation_error
from scholar_outbound_manager.tui.config_editor import save_config_draft
from scholar_outbound_manager.tui.config_editor import update_config_draft_text
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH


@dataclass(slots=True)
class ConfigFieldSpec:
    key: str
    title: str
    description: str
    value_type: str
    current_value: object
    draft_value: object
    editable: bool
    sensitive: bool
    requires_restart: bool
    validation_error: str | None


@dataclass(slots=True)
class ConfigFormState:
    fields: list[ConfigFieldSpec]
    dirty: bool
    valid: bool
    validation_errors: list[str]
    redacted_diff: str


_SAFE_FIELD_SPECS: tuple[dict[str, object], ...] = (
    {
        "key": "user_data_dir",
        "title": "User Data Directory",
        "description": "Root directory for TUI-managed artifacts and journals.",
        "value_type": "str",
        "requires_restart": False,
    },
    {
        "key": "subscription.user_agent",
        "title": "Subscription User-Agent",
        "description": "User-Agent header used for subscription fetch requests.",
        "value_type": "str",
        "requires_restart": False,
    },
    {
        "key": "probe.concurrency",
        "title": "Probe Concurrency",
        "description": "Maximum concurrent probe workers.",
        "value_type": "int",
        "requires_restart": False,
    },
    {
        "key": "probe.timeout_seconds",
        "title": "Probe Timeout Seconds",
        "description": "Per-request timeout for probe operations.",
        "value_type": "int",
        "requires_restart": False,
    },
    {
        "key": "probe.allow_network_probe",
        "title": "Allow Network Probe",
        "description": "Config-side gate for live probe execution.",
        "value_type": "bool",
        "requires_restart": False,
    },
    {
        "key": "xray.binary_path",
        "title": "Xray Binary Path",
        "description": "Local path to the managed Xray binary.",
        "value_type": "str",
        "requires_restart": True,
    },
    {
        "key": "xray.local_socks_host",
        "title": "Local SOCKS Host",
        "description": "Local bind host for the managed SOCKS runtime.",
        "value_type": "str",
        "requires_restart": True,
    },
    {
        "key": "xray.local_socks_port",
        "title": "Local SOCKS Port",
        "description": "Local bind port for the managed SOCKS runtime.",
        "value_type": "int",
        "requires_restart": True,
    },
    {
        "key": "routing.mode",
        "title": "Routing Mode",
        "description": "Routing strategy for managed Scholar traffic.",
        "value_type": "str",
        "requires_restart": True,
    },
    {
        "key": "routing.fail_closed",
        "title": "Routing Fail Closed",
        "description": "Whether routing should fail closed when no candidate is available.",
        "value_type": "bool",
        "requires_restart": True,
    },
    {
        "key": "sidecar.service_name",
        "title": "Managed Service Name",
        "description": "systemd unit name for the managed sidecar service.",
        "value_type": "str",
        "requires_restart": True,
    },
    {
        "key": "experimental.enable_hysteria2",
        "title": "Experimental Hysteria2",
        "description": "Enable experimental Hysteria2 handling in the TUI workflow.",
        "value_type": "bool",
        "requires_restart": True,
    },
)


def build_config_form_state(config_path: str | Path) -> ConfigFormState:
    """Build one structured, allowlisted config form state from the current config."""
    config_file = Path(config_path)
    draft = load_config_draft(config_file)
    errors = list(draft.validation_errors)
    try:
        parsed = load_config(config_file)
        raw = _load_yaml_mapping(config_file)
    except (ConfigError, OSError, ValueError, yaml.YAMLError) as exc:
        return ConfigFormState(fields=[], dirty=False, valid=False, validation_errors=errors or [redact_validation_error(str(exc))], redacted_diff="")

    fields: list[ConfigFieldSpec] = []
    for spec in _SAFE_FIELD_SPECS:
        key = str(spec["key"])
        current_value = _lookup_field_value(parsed, key, raw)
        fields.append(
            ConfigFieldSpec(
                key=key,
                title=str(spec["title"]),
                description=str(spec["description"]),
                value_type=str(spec["value_type"]),
                current_value=current_value,
                draft_value=current_value,
                editable=True,
                sensitive=False,
                requires_restart=bool(spec["requires_restart"]),
                validation_error=None,
            )
        )
    return ConfigFormState(
        fields=fields,
        dirty=False,
        valid=True,
        validation_errors=[],
        redacted_diff="",
    )


def build_config_patch_from_field_update(field_key: str, value: object) -> dict[str, object]:
    """Build one nested patch mapping from one allowlisted field update."""
    allowed = {str(spec["key"]) for spec in _SAFE_FIELD_SPECS}
    if field_key not in allowed:
        raise ValueError(f"Field '{field_key}' is not editable through the structured TUI form.")
    parts = field_key.split(".")
    patch: dict[str, object] = {}
    cursor: dict[str, object] = patch
    for part in parts[:-1]:
        nested: dict[str, object] = {}
        cursor[part] = nested
        cursor = nested
    cursor[parts[-1]] = value
    return patch


def apply_config_form_patch(
    config_path: str | Path,
    patch: dict[str, object],
    *,
    undo_journal_path: str | Path = DEFAULT_TUI_UNDO_JOURNAL_PATH,
):
    """Apply one safe structured patch through the transactional config draft layer."""
    config_file = Path(config_path)
    raw = _load_yaml_mapping(config_file)
    updated = _merge_patch(raw, patch)
    rendered = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
    draft = update_config_draft_text(load_config_draft(config_file), rendered)
    if not draft.parsed_ok:
        raise ValueError("Structured config patch is invalid and was not saved.")
    return save_config_draft(draft, undo_journal_path=undo_journal_path)


def _load_yaml_mapping(path: Path) -> dict[str, Any]:
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Configuration root must be a mapping.")
    return dict(payload)


def _merge_patch(base: dict[str, Any], patch: dict[str, object]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for key, value in base.items():
        if isinstance(value, dict):
            merged[key] = _merge_patch(value, {})
        else:
            merged[key] = value
    for key, value in patch.items():
        if isinstance(value, dict):
            base_child = merged.get(key, {})
            if not isinstance(base_child, dict):
                base_child = {}
            merged[key] = _merge_patch(dict(base_child), value)
        else:
            merged[key] = value
    return merged


def _lookup_field_value(parsed_config: object, field_key: str, raw: dict[str, Any]) -> object:
    parts = field_key.split(".")
    current: object = parsed_config
    for part in parts:
        if hasattr(current, part):
            current = getattr(current, part)
            continue
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        return _lookup_raw_value(raw, parts)
    return current


def _lookup_raw_value(raw: dict[str, Any], parts: list[str]) -> object:
    current: object = raw
    for part in parts:
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current
