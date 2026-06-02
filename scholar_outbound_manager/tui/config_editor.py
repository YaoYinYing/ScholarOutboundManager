"""Transactional config-draft helpers for the optional TUI control plane."""

from __future__ import annotations

import difflib
import hashlib
import json
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path

from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.tui.constants import DEFAULT_TUI_UNDO_JOURNAL_PATH
from scholar_outbound_manager.tui.view_model import redact_text


@dataclass(slots=True)
class ConfigDraft:
    """Represent one editable config draft plus validation state."""

    path: str
    original_text: str
    current_text: str
    parsed_ok: bool
    validation_errors: list[str]
    redacted_preview: str
    diff_preview: str
    dirty: bool


@dataclass(slots=True)
class ConfigSaveResult:
    """Describe one config save action."""

    path: str
    saved: bool
    dirty: bool
    parsed_ok: bool
    undo_journal_path: str
    created_at: str | None
    previous_sha256: str | None
    next_sha256: str | None


@dataclass(slots=True)
class ConfigUndoResult:
    """Describe one config undo action."""

    path: str
    restored: bool
    undo_journal_path: str
    restored_from_sha256: str | None
    restored_to_sha256: str | None
    created_at: str | None


def load_config_draft(path: str | Path) -> ConfigDraft:
    """Load one config file into a validated draft."""
    config_path = Path(path)
    original_text = config_path.read_text(encoding="utf-8")
    draft = ConfigDraft(
        path=str(config_path),
        original_text=original_text,
        current_text=original_text,
        parsed_ok=False,
        validation_errors=[],
        redacted_preview="",
        diff_preview="",
        dirty=False,
    )
    return validate_config_draft(draft)


def update_config_draft_text(draft: ConfigDraft, new_text: str) -> ConfigDraft:
    """Return one updated draft with revalidated text."""
    updated = ConfigDraft(
        path=draft.path,
        original_text=draft.original_text,
        current_text=new_text,
        parsed_ok=False,
        validation_errors=[],
        redacted_preview="",
        diff_preview="",
        dirty=new_text != draft.original_text,
    )
    return validate_config_draft(updated)


def validate_config_draft(draft: ConfigDraft) -> ConfigDraft:
    """Validate one config draft using the real config loader."""
    errors: list[str] = []
    try:
        _validate_config_text(draft.current_text)
        parsed_ok = True
    except (ConfigError, ValueError) as exc:
        parsed_ok = False
        errors.append(str(exc))
    return ConfigDraft(
        path=draft.path,
        original_text=draft.original_text,
        current_text=draft.current_text,
        parsed_ok=parsed_ok,
        validation_errors=errors,
        redacted_preview=build_redacted_config_preview(draft.current_text),
        diff_preview=build_config_diff(draft.original_text, draft.current_text),
        dirty=draft.current_text != draft.original_text,
    )


def build_config_diff(original_text: str, current_text: str) -> str:
    """Build one redacted unified diff preview."""
    original_preview = build_redacted_config_preview(original_text)
    current_preview = build_redacted_config_preview(current_text)
    diff_lines = list(
        difflib.unified_diff(
            original_preview.splitlines(),
            current_preview.splitlines(),
            fromfile="config.yaml",
            tofile="config.yaml",
            lineterm="",
        )
    )
    return "\n".join(diff_lines)


def build_redacted_config_preview(text: str) -> str:
    """Render one redacted config preview without secret values."""
    redacted = text
    patterns = [
        (r'(?im)^(\s*url\s*:\s*)(["\']?).*$', r'\1\2<REDACTED_URL>'),
        (
            r'(?im)^(\s*(?:password|auth|token|public[_ -]?key|private[_ -]?key|server_name|servername|sni|server|obfs-password|authorization|set[_ -]?cookie|cookie|api[_ -]?key|x[_ -]?api[_ -]?key|x[_ -]?auth[_ -]?token|access[_ -]?token|refresh[_ -]?token|client[_ -]?secret|secret|bearer)\s*:\s*)(["\']?).*$',
            r'\1\2<REDACTED>',
        ),
        (r"(?i)\bhttps?://[^\s\"']+", "<REDACTED_URL>"),
        (r"(?i)\b(?:vless|vmess|trojan|ss|hysteria2)://[^\s\"']+", "<REDACTED_URI>"),
        (r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", "<UUID>"),
    ]
    for pattern, replacement in patterns:
        redacted = re.sub(pattern, replacement, redacted)
    return redact_text(redacted)


def save_config_draft(
    draft: ConfigDraft,
    *,
    undo_journal_path: str | Path = DEFAULT_TUI_UNDO_JOURNAL_PATH,
) -> ConfigSaveResult:
    """Validate then atomically save one config draft and append undo history."""
    validated = validate_config_draft(draft)
    if not validated.parsed_ok:
        raise ValueError("Config draft is invalid and cannot be saved.")
    if not validated.dirty:
        return ConfigSaveResult(
            path=validated.path,
            saved=False,
            dirty=False,
            parsed_ok=True,
            undo_journal_path=str(undo_journal_path),
            created_at=None,
            previous_sha256=_sha256_text(validated.original_text),
            next_sha256=_sha256_text(validated.current_text),
        )

    created_at = _utc_now_iso8601()
    previous_sha256 = _sha256_text(validated.original_text)
    next_sha256 = _sha256_text(validated.current_text)
    entry = {
        "schema_version": 1,
        "created_at": created_at,
        "config_path": validated.path,
        "previous_sha256": previous_sha256,
        "next_sha256": next_sha256,
        "previous_text": validated.original_text,
        "next_redacted_summary": build_redacted_config_preview(validated.current_text),
        "reason": "tui_config_save",
    }
    _append_undo_entry(undo_journal_path, entry)
    _atomic_write_text(validated.path, validated.current_text)
    return ConfigSaveResult(
        path=validated.path,
        saved=True,
        dirty=False,
        parsed_ok=True,
        undo_journal_path=str(undo_journal_path),
        created_at=created_at,
        previous_sha256=previous_sha256,
        next_sha256=next_sha256,
    )


def undo_last_config_save(
    *,
    config_path: str | Path,
    undo_journal_path: str | Path = DEFAULT_TUI_UNDO_JOURNAL_PATH,
) -> ConfigUndoResult:
    """Restore the previous config text from the matching journal entry."""
    normalized_path = str(Path(config_path))
    entries = _load_undo_entries(undo_journal_path)
    current_text = Path(config_path).read_text(encoding="utf-8")
    target_entry = _find_matching_undo_save_entry(
        entries,
        config_path=normalized_path,
        current_sha256=_sha256_text(current_text),
    )
    if target_entry is None:
        raise ValueError("No compatible config undo entry is available for the current config state.")

    previous_text = str(target_entry["previous_text"])
    _validate_config_text(previous_text)
    _atomic_write_text(config_path, previous_text)

    created_at = _utc_now_iso8601()
    undo_entry = {
        "schema_version": 1,
        "created_at": created_at,
        "config_path": normalized_path,
        "previous_sha256": _sha256_text(current_text),
        "next_sha256": _sha256_text(previous_text),
        "previous_text": current_text,
        "next_redacted_summary": build_redacted_config_preview(previous_text),
        "reason": "tui_config_undo",
    }
    _append_undo_entry(undo_journal_path, undo_entry)
    return ConfigUndoResult(
        path=normalized_path,
        restored=True,
        undo_journal_path=str(undo_journal_path),
        restored_from_sha256=_coerce_optional_str(target_entry.get("next_sha256")),
        restored_to_sha256=_sha256_text(previous_text),
        created_at=created_at,
    )


def has_undo_journal_entry(
    *,
    config_path: str | Path,
    undo_journal_path: str | Path = DEFAULT_TUI_UNDO_JOURNAL_PATH,
) -> bool:
    """Return whether one compatible undo entry exists for the config."""
    config_file = Path(config_path)
    if not config_file.exists():
        return False
    normalized_path = str(Path(config_path))
    current_sha256 = _sha256_text(config_file.read_text(encoding="utf-8"))
    return (
        _find_matching_undo_save_entry(
            _load_undo_entries(undo_journal_path),
            config_path=normalized_path,
            current_sha256=current_sha256,
        )
        is not None
    )


def _find_matching_undo_save_entry(
    entries: list[dict[str, object]],
    *,
    config_path: str,
    current_sha256: str,
) -> dict[str, object] | None:
    for entry in reversed(entries):
        if str(entry.get("reason") or "") != "tui_config_save":
            continue
        if str(entry.get("config_path") or "") != config_path:
            continue
        if not isinstance(entry.get("previous_text"), str):
            continue
        if str(entry.get("next_sha256") or "") != current_sha256:
            continue
        return entry
    return None


def _append_undo_entry(path: str | Path, entry: dict[str, object]) -> None:
    entries = _load_undo_entries(path)
    entries.append({str(key): value for key, value in entry.items()})
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    rendered = "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True) for item in entries)
    if rendered:
        rendered += "\n"
    _atomic_write_text(target_path, rendered)


def _load_undo_entries(path: str | Path) -> list[dict[str, object]]:
    journal_path = Path(path)
    if not journal_path.exists():
        return []
    entries: list[dict[str, object]] = []
    for line in journal_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        payload = json.loads(line)
        if isinstance(payload, dict):
            entries.append({str(key): value for key, value in payload.items()})
    return entries


def _validate_config_text(text: str) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".yaml", delete=False) as handle:
        temp_path = Path(handle.name)
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())
    try:
        load_config(temp_path)
    finally:
        temp_path.unlink(missing_ok=True)


def _atomic_write_text(path: str | Path, text: str) -> None:
    target_path = Path(path)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=target_path.parent,
            prefix=f".{target_path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            temp_path = Path(handle.name)
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        temp_path.replace(target_path)
        _fsync_directory(target_path.parent)
    except Exception:
        if temp_path is not None:
            temp_path.unlink(missing_ok=True)
        raise


def _fsync_directory(directory: Path) -> None:
    if os.name != "posix":
        return
    try:
        directory_fd = os.open(directory, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    except OSError:
        pass
    finally:
        os.close(directory_fd)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _coerce_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value:
        return value
    return None
