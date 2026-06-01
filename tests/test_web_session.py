"""Tests for web session cookies and CSRF/session handling."""

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


def test_cookie_is_httponly_and_samesite_strict(tmp_path: Path) -> None:
    """Use conservative cookie attributes on successful login."""
    app = _make_app(tmp_path)
    users = load_users(app.config.auth_db_path)
    preauth_cookie = _start_password_login(app)

    response = app.handle(
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

    set_cookie = response.headers["set-cookie"]
    assert "HttpOnly" in set_cookie
    assert "SameSite=Strict" in set_cookie


def test_cookie_is_secure_on_https(tmp_path: Path) -> None:
    """Set Secure on HTTPS logins."""
    app = _make_app(tmp_path)
    users = load_users(app.config.auth_db_path)
    preauth_cookie = _start_password_login(app)

    response = app.handle(
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

    assert "Secure" in response.headers["set-cookie"]


def _make_app(tmp_path: Path) -> WebPanelApp:
    config = WebPanelConfig(
        session_secret_path=str(tmp_path / "state_data" / "web" / "session_secret"),
        auth_db_path=str(tmp_path / "state_data" / "web" / "users.json"),
        login_log_path=str(tmp_path / "state_data" / "web" / "auth.log"),
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
