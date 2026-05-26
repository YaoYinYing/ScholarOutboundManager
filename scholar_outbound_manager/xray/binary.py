"""Explicit Xray binary inspection and installation helpers."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path
from pathlib import PurePosixPath
from urllib.request import build_opener


@dataclass(frozen=True)
class XrayBinaryInfo:
    """Describe one local Xray binary candidate."""

    path: str
    exists: bool
    executable: bool
    version: str | None
    error: str | None


@dataclass(frozen=True)
class XrayPlatformAsset:
    """Describe one Xray release asset for a platform."""

    os_name: str
    arch: str
    asset_name: str


@dataclass(frozen=True)
class XrayDownloadPlan:
    """Describe one download/install plan for Xray."""

    version: str
    asset_name: str
    download_url: str
    output_path: str
    archive_path: str
    checksum_url: str | None


@dataclass(frozen=True)
class XrayInstallResult:
    """Describe one Xray install attempt."""

    binary_path: str
    version: str | None
    downloaded: bool
    installed: bool
    error: str | None


def inspect_xray_binary(path: str | Path, timeout_seconds: float = 5.0) -> XrayBinaryInfo:
    """Inspect one local Xray binary path without raising process errors."""
    binary_path = Path(path)
    if timeout_seconds <= 0:
        return XrayBinaryInfo(
            path=str(binary_path),
            exists=binary_path.exists(),
            executable=False,
            version=None,
            error="timeout_seconds must be greater than 0.",
        )

    if not binary_path.exists():
        return XrayBinaryInfo(
            path=str(binary_path),
            exists=False,
            executable=False,
            version=None,
            error=None,
        )
    if not binary_path.is_file():
        return XrayBinaryInfo(
            path=str(binary_path),
            exists=True,
            executable=False,
            version=None,
            error="Xray binary path is not a file.",
        )

    executable = os.access(binary_path, os.X_OK)
    if not executable:
        return XrayBinaryInfo(
            path=str(binary_path),
            exists=True,
            executable=False,
            version=None,
            error=None,
        )

    try:
        result = subprocess.run(
            [str(binary_path), "version"],
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as exc:
        return XrayBinaryInfo(
            path=str(binary_path),
            exists=True,
            executable=True,
            version=None,
            error=_safe_process_error(exc),
        )

    version = _extract_first_line(result.stdout)
    error = None
    if result.returncode != 0:
        error = f"Xray version command failed with return code {result.returncode}."
    return XrayBinaryInfo(
        path=str(binary_path),
        exists=True,
        executable=True,
        version=version,
        error=error,
    )


def detect_xray_platform(
    system: str | None = None,
    machine: str | None = None,
) -> XrayPlatformAsset:
    """Map the current platform to one supported Xray release asset."""
    os_name = system or platform.system()
    arch = machine or platform.machine()
    normalized_system = os_name.lower()
    normalized_arch = arch.lower()

    mapping = {
        ("linux", "x86_64"): "Xray-linux-64.zip",
        ("linux", "amd64"): "Xray-linux-64.zip",
        ("linux", "aarch64"): "Xray-linux-arm64-v8a.zip",
        ("linux", "arm64"): "Xray-linux-arm64-v8a.zip",
        ("darwin", "x86_64"): "Xray-macos-64.zip",
        ("darwin", "arm64"): "Xray-macos-arm64-v8a.zip",
        ("darwin", "aarch64"): "Xray-macos-arm64-v8a.zip",
    }
    asset_name = mapping.get((normalized_system, normalized_arch))
    if asset_name is None:
        raise ValueError(f"Unsupported Xray platform: {os_name}/{arch}.")
    return XrayPlatformAsset(os_name=os_name, arch=arch, asset_name=asset_name)


def build_xray_download_plan(
    version: str,
    install_dir: str | Path,
    platform_asset: XrayPlatformAsset | None = None,
    base_url: str = "https://github.com/XTLS/Xray-core/releases/download",
) -> XrayDownloadPlan:
    """Build one Xray download plan without accessing the network."""
    asset = platform_asset or detect_xray_platform()
    install_path = Path(install_dir)
    output_path = install_path / "xray"
    archive_path = install_path / asset.asset_name
    if version == "latest":
        download_url = f"https://github.com/XTLS/Xray-core/releases/latest/download/{asset.asset_name}"
    else:
        download_url = f"{base_url}/{version}/{asset.asset_name}"
    return XrayDownloadPlan(
        version=version,
        asset_name=asset.asset_name,
        download_url=download_url,
        output_path=str(output_path),
        archive_path=str(archive_path),
        checksum_url=None,
    )


def download_file(
    url: str,
    destination: str | Path,
    timeout_seconds: float = 60.0,
    max_bytes: int = 100 * 1024 * 1024,
    opener: object | None = None,
) -> None:
    """Download one file atomically without exposing the source URL in errors."""
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than 0.")
    if max_bytes <= 0:
        raise ValueError("max_bytes must be greater than 0.")

    target_path = Path(destination)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = target_path.with_name(f"{target_path.name}.tmp")
    transport = opener if opener is not None else build_opener()

    try:
        with transport.open(url, timeout=timeout_seconds) as response, temp_path.open("wb") as handle:
            total_bytes = 0
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    break
                total_bytes += len(chunk)
                if total_bytes > max_bytes:
                    raise ValueError("Downloaded file exceeds the configured byte limit.")
                handle.write(chunk)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    temp_path.replace(target_path)


def install_xray_from_archive(
    archive_path: str | Path,
    install_dir: str | Path,
) -> str:
    """Install the Xray binary from a zip archive into the requested directory."""
    archive = Path(archive_path)
    install_path = Path(install_dir)
    if archive.suffix.lower() != ".zip":
        raise ValueError("Only zip archives are supported for Xray installation.")

    install_path.mkdir(parents=True, exist_ok=True)
    output_path = install_path / "xray"

    with zipfile.ZipFile(archive, "r") as bundle:
        for member in bundle.infolist():
            normalized = PurePosixPath(member.filename)
            if normalized.is_absolute() or ".." in normalized.parts:
                continue
            if normalized.name not in {"xray", "xray.exe"}:
                continue
            with bundle.open(member, "r") as source, output_path.open("wb") as destination:
                shutil.copyfileobj(source, destination)
            output_path.chmod(0o755)
            return str(output_path)

    raise ValueError("Xray archive does not contain an xray executable.")


def install_xray_binary(
    version: str,
    install_dir: str | Path,
    *,
    allow_download: bool,
    platform_asset: XrayPlatformAsset | None = None,
    downloader=download_file,
) -> XrayInstallResult:
    """Download and install Xray only when explicit download opt-in is enabled."""
    plan = build_xray_download_plan(version, install_dir, platform_asset=platform_asset)
    Path(install_dir).mkdir(parents=True, exist_ok=True)
    if not allow_download:
        return XrayInstallResult(
            binary_path=plan.output_path,
            version=None,
            downloaded=False,
            installed=False,
            error="Downloading Xray requires explicit opt-in.",
        )

    downloaded = False
    try:
        downloader(plan.download_url, plan.archive_path)
        downloaded = True
        binary_path = install_xray_from_archive(plan.archive_path, install_dir)
        info = inspect_xray_binary(binary_path)
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        return XrayInstallResult(
            binary_path=plan.output_path,
            version=None,
            downloaded=downloaded,
            installed=False,
            error=str(exc),
        )

    return XrayInstallResult(
        binary_path=binary_path,
        version=info.version,
        downloaded=True,
        installed=info.exists and info.executable and info.error is None,
        error=info.error,
    )


def _extract_first_line(text: str) -> str | None:
    """Return the first non-empty line from command output."""
    for line in text.splitlines():
        stripped = line.strip()
        if stripped:
            return stripped
    return None


def _safe_process_error(exc: Exception) -> str:
    """Return a bounded process error string."""
    if isinstance(exc, subprocess.TimeoutExpired):
        return "Xray version command timed out."
    if isinstance(exc, FileNotFoundError):
        return "Xray binary could not be executed."
    if isinstance(exc, OSError):
        return str(exc).split(":")[0] or "Xray binary could not be executed."
    return "Xray binary could not be executed."
