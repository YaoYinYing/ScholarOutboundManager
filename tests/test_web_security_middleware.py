"""Tests for web security helpers and request enforcement."""

from __future__ import annotations

import base64
import hmac
import struct
import time
from pathlib import Path
from hashlib import sha1

from scholar_outbound_manager.web.app import WebPanelApp
from scholar_outbound_manager.web.app import WebRequest
from scholar_outbound_manager.web.auth import create_user
from scholar_outbound_manager.web.auth import load_users
from scholar_outbound_manager.web.auth import write_users
from scholar_outbound_manager.web.config import WebPanelConfig
from scholar_outbound_manager.web.security import ensure_not_running_as_root


def test_localhost_http_allowed_when_configured(tmp_path: Path) -> None:
    """Allow localhost HTTP for SSH-forward style access."""
    app = _make_app(tmp_path, trusted_proxy_headers=False)

    response = app.handle(WebRequest(method="GET", path="/login", headers={}, host="127.0.0.1", scheme="http"))
    assert response.status_code == 200


def test_non_localhost_http_rejected(tmp_path: Path) -> None:
    """Reject non-localhost HTTP when HTTPS is required."""
    app = _make_app(tmp_path, trusted_proxy_headers=False)

    response = app.handle(WebRequest(method="GET", path="/login", headers={}, host="panel.example.com", scheme="http", client_ip="203.0.113.5"))
    assert response.status_code == 403


def test_forwarded_proto_ignored_unless_trusted_proxy_enabled(tmp_path: Path) -> None:
    """Ignore X-Forwarded-Proto unless the app is configured to trust it."""
    app = _make_app(tmp_path, trusted_proxy_headers=False)
    rejected = app.handle(
        WebRequest(method="GET", path="/login", headers={"x-forwarded-proto": "https"}, host="panel.example.com", scheme="http")
    )

    trusted_app = _make_app(tmp_path / "trusted", trusted_proxy_headers=True)
    allowed = trusted_app.handle(
        WebRequest(method="GET", path="/login", headers={"x-forwarded-proto": "https"}, host="panel.example.com", scheme="http")
    )

    assert rejected.status_code == 403
    assert allowed.status_code == 200


def test_csrf_required_for_post(tmp_path: Path) -> None:
    """Require CSRF on mutating POST endpoints."""
    app = _make_app(tmp_path, trusted_proxy_headers=False)
    users = load_users(app.config.auth_db_path)
    preauth_cookie = _start_password_login(app)
    login_response = app.handle(
        WebRequest(
            method="POST",
            path="/login/totp",
            headers={"content-type": "application/x-www-form-urlencoded"},
            form={"totp_code": _totp_code(users["admin"].totp_secret or "")},
            cookies={app.config.session_cookie_name: preauth_cookie},
            scheme="https",
            host="panel.example.com",
        )
    )
    cookie_value = login_response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]

    response = app.handle(
        WebRequest(
            method="POST",
            path="/api/echo",
            headers={"content-type": "application/json"},
            json_body={"message": "hello"},
            cookies={app.config.session_cookie_name: cookie_value},
            scheme="https",
            host="panel.example.com",
        )
    )
    assert response.status_code == 403


def test_get_cannot_mutate(tmp_path: Path) -> None:
    """Reject GET on state-changing routes."""
    app = _make_app(tmp_path, trusted_proxy_headers=False)
    response = app.handle(WebRequest(method="GET", path="/logout", headers={}, host="127.0.0.1"))
    assert response.status_code == 405


def test_root_process_refused_unless_explicitly_allowed() -> None:
    """Refuse root process execution by default."""
    try:
        ensure_not_running_as_root(allow_root_process=False, geteuid=lambda: 0)
    except ValueError as exc:
        assert "refused by default" in str(exc)
    else:
        raise AssertionError("Expected root process refusal.")

    ensure_not_running_as_root(allow_root_process=True, geteuid=lambda: 0)


def _make_app(tmp_path: Path, *, trusted_proxy_headers: bool) -> WebPanelApp:
    config = WebPanelConfig(
        session_secret_path=str(tmp_path / "state_data" / "web" / "session_secret"),
        auth_db_path=str(tmp_path / "state_data" / "web" / "users.json"),
        login_log_path=str(tmp_path / "state_data" / "web" / "auth.log"),
        trusted_proxy_headers=trusted_proxy_headers,
    )
    user = create_user(username="admin", password="correct-password", created_at="2026-06-01T00:00:00Z")
    write_users(config.auth_db_path, {"admin": user})
    return WebPanelApp(config)


def _start_password_login(app: WebPanelApp) -> str:
    response = app.handle(
        WebRequest(
            method="POST",
            path="/login/password",
            headers={"content-type": "application/x-www-form-urlencoded"},
            form={"username": "admin", "password": "correct-password"},
            client_ip="203.0.113.5",
        )
    )
    return response.headers["set-cookie"].split(";", 1)[0].split("=", 1)[1]


def _totp_code(secret: str, *, for_time: int | None = None) -> str:
    normalized = secret.upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding)
    current = int(time.time()) if for_time is None else for_time
    counter = int(current // 30)
    digest = hmac.new(key, struct.pack(">Q", counter), sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % 1_000_000).zfill(6)
