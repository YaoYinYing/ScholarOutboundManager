"""Tests for web API auth, method, and content-type guards."""

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


def test_api_requires_auth(tmp_path: Path) -> None:
    """Protect /api endpoints with authenticated sessions."""
    app = _make_app(tmp_path)
    response = app.handle(WebRequest(method="GET", path="/api/ping", headers={}, scheme="https", host="panel.example.com"))
    assert response.status_code == 401


def test_unknown_method_returns_405(tmp_path: Path) -> None:
    """Restrict API methods to explicit allowlists."""
    app = _make_app(tmp_path)
    response = app.handle(WebRequest(method="PUT", path="/api/ping", headers={}, scheme="https", host="panel.example.com"))
    assert response.status_code == 405


def test_wrong_content_type_rejected(tmp_path: Path) -> None:
    """Reject mutating JSON APIs with the wrong content type."""
    app = _make_app(tmp_path)
    cookie_value, csrf_token = _login_and_csrf(app)

    response = app.handle(
        WebRequest(
            method="POST",
            path="/api/echo",
            headers={"content-type": "text/plain", "x-csrf-token": csrf_token},
            json_body={"message": "hello"},
            cookies={app.config.session_cookie_name: cookie_value},
            scheme="https",
            host="panel.example.com",
        )
    )
    assert response.status_code == 415


def test_no_route_returns_raw_sensitive_artifact(tmp_path: Path) -> None:
    """Keep web responses free of sensitive artifact payloads."""
    app = _make_app(tmp_path)
    login_page = app.handle(WebRequest(method="GET", path="/login", headers={}, host="127.0.0.1"))
    index_page = app.handle(WebRequest(method="GET", path="/", headers={}, host="127.0.0.1"))
    rendered = login_page.body + index_page.body

    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "candidates.json" not in rendered


def test_templates_do_not_include_secret_values() -> None:
    """Keep web templates free of baked-in secrets."""
    template_root = Path("scholar_outbound_manager/web/templates")
    rendered = "\n".join(path.read_text(encoding="utf-8") for path in template_root.glob("*.html"))

    assert "raw_uri" not in rendered
    assert "PUBLIC_KEY_PLACEHOLDER" not in rendered
    assert "PASSWORD_PLACEHOLDER" not in rendered


def _make_app(tmp_path: Path) -> WebPanelApp:
    config = WebPanelConfig(
        session_secret_path=str(tmp_path / "state_data" / "web" / "session_secret"),
        auth_db_path=str(tmp_path / "state_data" / "web" / "users.json"),
        login_log_path=str(tmp_path / "state_data" / "web" / "auth.log"),
    )
    user = create_user(username="admin", password="correct-password", created_at="2026-06-01T00:00:00Z")
    write_users(config.auth_db_path, {"admin": user})
    return WebPanelApp(config)


def _login_and_csrf(app: WebPanelApp) -> tuple[str, str]:
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
    csrf_token = cookie_value.split(".", 1)[1]
    return cookie_value, csrf_token


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
