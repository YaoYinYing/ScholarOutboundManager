"""Tests for web CLI entry points."""

from __future__ import annotations

import io
import json
from pathlib import Path

from scholar_outbound_manager import cli


def test_web_serve_without_dependencies_prints_install_hint(capsys) -> None:
    """Explain how to install the optional web stack."""
    exit_code = cli.main(["web", "serve"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert 'pip install "ScholarOutboundManager[web]"' in captured.out or 'pip install "ScholarOutboundManager[web]"' in captured.err


def test_web_user_init_rejects_root_username(tmp_path: Path, capsys, monkeypatch) -> None:
    """Reject root web usernames at the CLI."""
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-password\n"))
    exit_code = cli.main(
        ["web", "user-init", "--username", "root", "--password-stdin", "--auth-db", str(tmp_path / "users.json")]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "root is forbidden" in captured.err


def test_web_user_init_writes_hash_not_plaintext(tmp_path: Path, capsys, monkeypatch) -> None:
    """Write a hashed password and one-time TOTP output."""
    auth_db = tmp_path / "users.json"
    totp_path = tmp_path / "totp.txt"
    monkeypatch.setattr("sys.stdin", io.StringIO("secret-password\n"))

    exit_code = cli.main(
        [
            "web",
            "user-init",
            "--username",
            "admin",
            "--password-stdin",
            "--auth-db",
            str(auth_db),
            "--totp-secret-output",
            str(totp_path),
        ]
    )
    captured = capsys.readouterr()
    payload = json.loads(auth_db.read_text(encoding="utf-8"))

    assert exit_code == 0
    assert "Initialized web user: admin" in captured.out
    assert payload["admin"]["password_hash"] != "secret-password"
    assert "secret-password" not in auth_db.read_text(encoding="utf-8")
    assert totp_path.exists()
