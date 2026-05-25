"""Atomic file writing helpers for generated JSON artifacts."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: str | Path, data: object) -> None:
    """Write JSON data atomically to the target path."""
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
            json.dump(data, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())

        temp_path.replace(target_path)
        _fsync_directory(target_path.parent)
    except Exception:
        if temp_path is not None:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                pass
        raise


def _fsync_directory(directory: Path) -> None:
    """Synchronize a directory entry when the platform supports it."""
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
