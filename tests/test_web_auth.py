"""Tests for web authentication helpers and login flow."""

from __future__ import annotations

import base64
import hmac
import json
import struct
import time
from hashlib import sha1
from pathlib import Path

import scholar_outbound_manager

from scholar_outbound_manager.web.app import WebPanelApp
from scholar_outbound_manager.web.app import WebRequest
from scholar_outbound_manager.web.app import init_user_from_stdin
from scholar_outbound_manager.web.auth import create_user
from scholar_outbound_manager.web.auth import load_users
from scholar_outbound_manager.web.auth import write_users
from scholar_outbound_manager.web.config import WebPanelConfig


def test_core_import_works_without_web_extra() -> None:
    """Keep the core package import independent from web extras."""
    assert hasattr(scholar_outbound_manager, "__version__")


def test_user_init_rejects_root_username(tmp_path: Path) -> None:
    """Forbid root as a web-panel login username."""
    try:
        init_user_from_stdin(username="root", password="secret", auth_db_path=tmp_path / "users.json")
    except ValueError as exc:
        assert "root is forbidden" in str(exc)
    else:
        raise AssertionError("Expected root username rejection.")


def test_user_init_writes_password_hash_and_totp_secret(tmp_path: Path) -> None:
    """Persist only password hashes and generate a TOTP secret."""
    auth_db = tmp_path / "users.json"
    secret_path = tmp_path / "totp.txt"

    result = init_user_from_stdin(
        username="admin",
        password="correct horse battery staple",
        auth_db_path=auth_db,
        totp_secret_output_path=secret_path,
    )
    users = load_users(auth_db)

    assert result["username"] == "admin"
    assert users["admin"].password_hash != "correct horse battery staple"
    assert users["admin"].totp_secret
    assert secret_path.exists()
    assert "otpauth://totp/" in secret_path.read_text(encoding="utf-8")


def test_login_with_wrong_password_logs_login_failed(tmp_path: Path) -> None:
    """Log failed password authentication without leaking secrets."""
    app = _make_app_with_user(tmp_path)

    response = app.handle(
        WebRequest(
            method="POST",
            path="/login/password",
            headers={"content-type": "application/x-www-form-urlencoded"},
            form={"username": "admin", "password": "wrong-password"},
            client_ip="203.0.113.5",
        )
    )

    log_text = Path(app.config.login_log_path).read_text(encoding="utf-8")
    assert response.status_code == 401
    assert "Invalid credentials" in response.body
    assert "event=login_failed" in log_text
    assert "src=203.0.113.5" in log_text
    assert "wrong-password" not in log_text


def test_login_with_wrong_totp_logs_totp_failed(tmp_path: Path) -> None:
    """Log failed TOTP verification without leaking the submitted code."""
    app = _make_app_with_user(tmp_path)
    preauth_cookie = _start_password_login(app)

    response = app.handle(
        WebRequest(
            method="POST",
            path="/login/totp",
            headers={"content-type": "application/x-www-form-urlencoded"},
            form={"totp_code": "000000"},
            cookies={app.config.session_cookie_name: preauth_cookie},
            client_ip="203.0.113.5",
        )
    )

    log_text = Path(app.config.login_log_path).read_text(encoding="utf-8")
    assert response.status_code == 401
    assert "event=totp_failed" in log_text
    assert "000000" not in log_text


def test_login_success_sets_cookie(tmp_path: Path) -> None:
    """Require password plus TOTP and set an opaque session cookie on success."""
    app = _make_app_with_user(tmp_path)
    users = load_users(app.config.auth_db_path)
    preauth_cookie = _start_password_login(app)
    totp_code = _totp_code(users["admin"].totp_secret or "")

    response = app.handle(
        WebRequest(
            method="POST",
            path="/login/totp",
            headers={"content-type": "application/x-www-form-urlencoded"},
            form={"totp_code": totp_code},
            cookies={app.config.session_cookie_name: preauth_cookie},
            scheme="https",
            host="panel.example.com",
            client_ip="203.0.113.5",
        )
    )

    assert response.status_code == 303
    assert "set-cookie" in response.headers
    assert "HttpOnly" in response.headers["set-cookie"]


def _make_app_with_user(tmp_path: Path) -> WebPanelApp:
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
    assert response.status_code == 303
    set_cookie = response.headers["set-cookie"]
    return set_cookie.split(";", 1)[0].split("=", 1)[1]


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
