"""Local artifact snapshot and rollback helpers for the TUI control plane."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import asdict
from dataclasses import dataclass
from datetime import datetime
from datetime import timezone
from pathlib import Path


@dataclass(slots=True)
class ArtifactSnapshotFile:
    logical_name: str
    original_path: str
    snapshot_path: str
    sha256: str
    exists: bool
    sensitive: bool


@dataclass(slots=True)
class ArtifactSnapshot:
    schema_version: int
    snapshot_id: str
    created_at: str
    reason: str
    files: dict[str, ArtifactSnapshotFile]


@dataclass(slots=True)
class ArtifactRollbackResult:
    restored: bool
    snapshot_id: str
    restored_files: list[str]
    missing_files: list[str]
    message: str


def create_artifact_snapshot(
    *,
    reason: str,
    candidates_path: str | Path = "candidates.json",
    probe_summary_path: str | Path = "state_data/probe_summary.json",
    passed_candidates_path: str | Path = "state_data/passed_candidates.json",
    selected_candidate_path: str | Path = "state_data/selected_candidate.json",
    pool_plan_path: str | Path = "state_data/sidecar_pool_plan.json",
    snapshot_root: str | Path = "state_data/tui/artifact_snapshots",
) -> ArtifactSnapshot:
    """Create one local artifact snapshot without exposing file content."""
    snapshot_id = _build_snapshot_id()
    snapshot_dir = Path(snapshot_root) / snapshot_id
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "candidates": _snapshot_one("candidates", candidates_path, snapshot_dir),
        "probe_summary": _snapshot_one("probe_summary", probe_summary_path, snapshot_dir),
        "passed_candidates": _snapshot_one("passed_candidates", passed_candidates_path, snapshot_dir),
        "selected_candidate": _snapshot_one("selected_candidate", selected_candidate_path, snapshot_dir),
        "pool_plan": _snapshot_one("pool_plan", pool_plan_path, snapshot_dir),
    }
    snapshot = ArtifactSnapshot(
        schema_version=1,
        snapshot_id=snapshot_id,
        created_at=_utc_now_iso8601(),
        reason=reason,
        files=files,
    )
    (snapshot_dir / "snapshot.json").write_text(json.dumps(asdict(snapshot), ensure_ascii=False, sort_keys=True, indent=2), encoding="utf-8")
    return snapshot


def list_artifact_snapshots(snapshot_root: str | Path) -> list[ArtifactSnapshot]:
    """List available local artifact snapshots newest-first."""
    root = Path(snapshot_root)
    if not root.exists():
        return []
    snapshots: list[ArtifactSnapshot] = []
    for metadata_path in sorted(root.glob("*/snapshot.json"), reverse=True):
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        files = {
            key: ArtifactSnapshotFile(**value)
            for key, value in dict(payload.get("files") or {}).items()
            if isinstance(value, dict)
        }
        snapshots.append(
            ArtifactSnapshot(
                schema_version=int(payload.get("schema_version") or 1),
                snapshot_id=str(payload.get("snapshot_id") or metadata_path.parent.name),
                created_at=str(payload.get("created_at") or ""),
                reason=str(payload.get("reason") or ""),
                files=files,
            )
        )
    return snapshots


def rollback_artifact_snapshot(
    snapshot_id: str,
    *,
    snapshot_root: str | Path = "state_data/tui/artifact_snapshots",
) -> ArtifactRollbackResult:
    """Restore one artifact snapshot back into the workspace."""
    snapshot_dir = Path(snapshot_root) / snapshot_id
    metadata_path = snapshot_dir / "snapshot.json"
    if not metadata_path.exists():
        raise ValueError(f"Artifact snapshot '{snapshot_id}' does not exist.")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    files = dict(payload.get("files") or {})
    restored_files: list[str] = []
    missing_files: list[str] = []
    for entry in files.values():
        if not isinstance(entry, dict):
            continue
        source = Path(str(entry.get("snapshot_path") or ""))
        target = Path(str(entry.get("original_path") or ""))
        if bool(entry.get("exists")) is not True:
            missing_files.append(str(target))
            continue
        if not source.exists():
            missing_files.append(str(target))
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)
        restored_files.append(str(target))
    message = "Artifact snapshot restored local files only; network and systemd side effects were not undone."
    return ArtifactRollbackResult(
        restored=bool(restored_files),
        snapshot_id=snapshot_id,
        restored_files=restored_files,
        missing_files=missing_files,
        message=message,
    )


def _snapshot_one(logical_name: str, source_path: str | Path, snapshot_dir: Path) -> ArtifactSnapshotFile:
    source = Path(source_path)
    target = snapshot_dir / f"{logical_name}.bin"
    if not source.exists():
        return ArtifactSnapshotFile(
            logical_name=logical_name,
            original_path=str(source),
            snapshot_path=str(target),
            sha256="",
            exists=False,
            sensitive=True,
        )
    shutil.copy2(source, target)
    return ArtifactSnapshotFile(
        logical_name=logical_name,
        original_path=str(source),
        snapshot_path=str(target),
        sha256=_sha256_file(target),
        exists=True,
        sensitive=True,
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _build_snapshot_id() -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    suffix = hashlib.sha256(timestamp.encode("utf-8")).hexdigest()[:6]
    return f"snap-{timestamp}-{suffix}"


def _utc_now_iso8601() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
