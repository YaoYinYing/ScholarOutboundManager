"""Tests for web-panel audit logging."""

from __future__ import annotations

from pathlib import Path

from scholar_outbound_manager.web.audit import write_auth_log


def test_auth_logs_are_fail2ban_friendly_and_redacted(tmp_path: Path) -> None:
    """Write line-oriented auth logs without secrets."""
    log_path = tmp_path / "auth.log"
    line = write_auth_log(
        log_path,
        event="login_failed",
        user="alice",
        src="203.0.113.5",
        reason="password=secret totp=123456 session=abcd vless://secret@example.invalid",
        ts="2026-06-01T00:00:00Z",
    )

    rendered = log_path.read_text(encoding="utf-8")
    assert line.startswith("SOMWEB_AUTH event=login_failed user=alice src=203.0.113.5")
    assert "password=secret" not in rendered
    assert "123456" not in rendered
    assert "vless://" not in rendered
    assert "src=203.0.113.5" in rendered
