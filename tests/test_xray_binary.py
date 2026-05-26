"""Tests for explicit Xray binary helpers."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from scholar_outbound_manager.xray.binary import XrayDownloadPlan
from scholar_outbound_manager.xray.binary import build_xray_download_plan
from scholar_outbound_manager.xray.binary import detect_xray_platform
from scholar_outbound_manager.xray.binary import download_file
from scholar_outbound_manager.xray.binary import inspect_xray_binary
from scholar_outbound_manager.xray.binary import install_xray_binary
from scholar_outbound_manager.xray.binary import install_xray_from_archive


def test_inspect_xray_binary_missing_path(tmp_path) -> None:
    """Report a missing binary path without raising."""
    info = inspect_xray_binary(tmp_path / "missing-xray")

    assert info.exists is False
    assert info.executable is False
    assert info.version is None


def test_inspect_xray_binary_existing_non_executable(tmp_path) -> None:
    """Report a non-executable file without trying to run it."""
    binary_path = tmp_path / "xray"
    binary_path.write_text("#!/bin/sh\necho hello\n", encoding="utf-8")
    binary_path.chmod(0o644)

    info = inspect_xray_binary(binary_path)

    assert info.exists is True
    assert info.executable is False
    assert info.version is None


def test_inspect_xray_binary_fake_executable_returns_version_first_line(tmp_path) -> None:
    """Read the first stdout line from a fake executable."""
    binary_path = _write_fake_executable(
        tmp_path / "xray",
        "#!/bin/sh\nprintf 'Xray 1.2.3\\nextra line\\n'\n",
    )

    info = inspect_xray_binary(binary_path)

    assert info.exists is True
    assert info.executable is True
    assert info.version == "Xray 1.2.3"
    assert info.error is None


def test_detect_xray_platform_linux_x86_64() -> None:
    asset = detect_xray_platform(system="Linux", machine="x86_64")
    assert asset.asset_name == "Xray-linux-64.zip"


def test_detect_xray_platform_linux_arm64() -> None:
    asset = detect_xray_platform(system="Linux", machine="arm64")
    assert asset.asset_name == "Xray-linux-arm64-v8a.zip"


def test_detect_xray_platform_darwin_arm64() -> None:
    asset = detect_xray_platform(system="Darwin", machine="arm64")
    assert asset.asset_name == "Xray-macos-arm64-v8a.zip"


def test_detect_xray_platform_unsupported_platform() -> None:
    with pytest.raises(ValueError, match="Unsupported Xray platform"):
        detect_xray_platform(system="Windows", machine="amd64")


def test_build_xray_download_plan_latest(tmp_path) -> None:
    plan = build_xray_download_plan(
        version="latest",
        install_dir=tmp_path,
        platform_asset=detect_xray_platform(system="Linux", machine="x86_64"),
    )

    assert plan.download_url.endswith("/latest/download/Xray-linux-64.zip")
    assert plan.output_path == str(tmp_path / "xray")


def test_build_xray_download_plan_fixed_version(tmp_path) -> None:
    plan = build_xray_download_plan(
        version="v26.5.9",
        install_dir=tmp_path,
        platform_asset=detect_xray_platform(system="Darwin", machine="arm64"),
    )

    assert plan.download_url.endswith("/download/v26.5.9/Xray-macos-arm64-v8a.zip")
    assert plan.archive_path == str(tmp_path / "Xray-macos-arm64-v8a.zip")


def test_download_file_writes_via_fake_opener(tmp_path) -> None:
    """Write a download through an injected fake opener."""
    destination = tmp_path / "artifact.zip"

    class FakeOpener:
        def open(self, url, timeout=60.0):
            assert timeout == 60.0
            assert url == "https://example.invalid/artifact.zip"
            return io.BytesIO(b"payload")

    download_file("https://example.invalid/artifact.zip", destination, opener=FakeOpener())

    assert destination.read_bytes() == b"payload"


def test_download_file_enforces_max_bytes(tmp_path) -> None:
    """Reject oversized downloads."""
    destination = tmp_path / "artifact.zip"

    class FakeOpener:
        def open(self, url, timeout=60.0):
            return io.BytesIO(b"payload")

    with pytest.raises(ValueError, match="byte limit"):
        download_file("https://example.invalid/artifact.zip", destination, max_bytes=3, opener=FakeOpener())


def test_install_xray_from_archive_extracts_xray(tmp_path) -> None:
    """Extract and chmod the xray binary from a zip archive."""
    archive_path = _write_fake_zip(tmp_path / "xray.zip", {"xray": b"#!/bin/sh\necho Xray 1.2.3\n"})

    binary_path = install_xray_from_archive(archive_path, tmp_path / "runtime")

    assert Path(binary_path).exists()
    assert Path(binary_path).name == "xray"


def test_install_xray_from_archive_rejects_archive_without_xray(tmp_path) -> None:
    archive_path = _write_fake_zip(tmp_path / "xray.zip", {"readme.txt": b"no binary"})

    with pytest.raises(ValueError, match="does not contain an xray executable"):
        install_xray_from_archive(archive_path, tmp_path / "runtime")


def test_install_xray_from_archive_prevents_zip_slip(tmp_path) -> None:
    """Ignore path traversal entries and still fail safely if nothing valid remains."""
    archive_path = _write_fake_zip(tmp_path / "xray.zip", {"../../xray": b"bad"})

    with pytest.raises(ValueError, match="does not contain an xray executable"):
        install_xray_from_archive(archive_path, tmp_path / "runtime")


def test_install_xray_binary_with_allow_download_false_does_not_call_downloader(tmp_path) -> None:
    """Do not call the downloader without explicit opt-in."""
    called = {"downloader": False}

    def fake_downloader(*args, **kwargs):
        called["downloader"] = True

    result = install_xray_binary(
        version="latest",
        install_dir=tmp_path / "runtime",
        allow_download=False,
        platform_asset=detect_xray_platform(system="Linux", machine="x86_64"),
        downloader=fake_downloader,
    )

    assert called["downloader"] is False
    assert result.installed is False
    assert result.downloaded is False
    assert result.error is not None


def test_install_xray_binary_with_fake_downloader_installs_fake_xray(tmp_path) -> None:
    """Install a fake Xray zip through the downloader hook."""
    runtime_dir = tmp_path / "runtime"

    def fake_downloader(url: str, destination: str | Path) -> None:
        assert "github.com/XTLS/Xray-core/releases" in url
        _write_fake_zip(
            Path(destination),
            {"Xray-linux-64/xray": b"#!/bin/sh\nprintf 'Xray 1.2.3\\n'\n"},
        )

    result = install_xray_binary(
        version="latest",
        install_dir=runtime_dir,
        allow_download=True,
        platform_asset=detect_xray_platform(system="Linux", machine="x86_64"),
        downloader=fake_downloader,
    )

    assert result.installed is True
    assert result.downloaded is True
    assert result.version == "Xray 1.2.3"
    assert Path(result.binary_path).exists()


def test_xray_binary_functions_do_not_print(tmp_path, capsys) -> None:
    """Keep helper functions side-effect free."""
    inspect_xray_binary(tmp_path / "missing-xray")
    build_xray_download_plan(
        version="latest",
        install_dir=tmp_path,
        platform_asset=detect_xray_platform(system="Linux", machine="x86_64"),
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def _write_fake_executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="utf-8")
    path.chmod(0o755)
    return path


def _write_fake_zip(path: Path, entries: dict[str, bytes]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return path
