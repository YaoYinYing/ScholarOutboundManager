"""Local web-panel foundation with dependency-gated serve entry point."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.web.audit import write_auth_log
from scholar_outbound_manager.web.auth import LoginAttemptTracker
from scholar_outbound_manager.web.auth import attempt_key
from scholar_outbound_manager.web.auth import build_otpauth_uri
from scholar_outbound_manager.web.auth import create_user
from scholar_outbound_manager.web.auth import load_users
from scholar_outbound_manager.web.auth import validate_totp_code
from scholar_outbound_manager.web.auth import validate_username
from scholar_outbound_manager.web.auth import verify_password
from scholar_outbound_manager.web.auth import verify_totp_code
from scholar_outbound_manager.web.auth import write_users
from scholar_outbound_manager.web.config import WebPanelConfig
from scholar_outbound_manager.web.config import ensure_session_secret
from scholar_outbound_manager.web.config import ensure_web_storage
from scholar_outbound_manager.web.config import session_store_path_for
from scholar_outbound_manager.web.security import ensure_bind_allowed
from scholar_outbound_manager.web.security import ensure_not_running_as_root
from scholar_outbound_manager.web.security import require_secure_request
from scholar_outbound_manager.web.security import security_headers
from scholar_outbound_manager.web.security import validate_content_type
from scholar_outbound_manager.web.session import SessionStore
from scholar_outbound_manager.web.session import build_expire_cookie_header
from scholar_outbound_manager.web.session import build_set_cookie_header
from scholar_outbound_manager.web.session import split_cookie_value
from scholar_outbound_manager.web.session import verify_csrf_token


@dataclass(slots=True)
class WebRequest:
    """Represent one synthetic web request for tests and adapters."""

    method: str
    path: str
    headers: dict[str, str]
    form: dict[str, str] | None = None
    json_body: dict[str, object] | None = None
    cookies: dict[str, str] | None = None
    client_ip: str = "127.0.0.1"
    scheme: str = "http"
    host: str = "127.0.0.1"


@dataclass(slots=True)
class WebResponse:
    """Represent one synthetic web response."""

    status_code: int
    headers: dict[str, str]
    body: str


class WebPanelApp:
    """Implement the secure foundation routes for the optional web panel."""

    def __init__(self, config: WebPanelConfig) -> None:
        self.config = config
        ensure_web_storage(config)
        self.session_secret = ensure_session_secret(config.session_secret_path)
        self.session_store = SessionStore(session_store_path_for(config))
        self.login_tracker = LoginAttemptTracker(
            limit=config.failed_login_limit,
            window_seconds=config.failed_login_window_seconds,
            lockout_seconds=config.lockout_seconds,
        )

    def handle(self, request: WebRequest) -> WebResponse:
        decision = require_secure_request(
            scheme=request.scheme,
            host=request.host,
            allow_insecure_localhost_http=self.config.allow_insecure_localhost_http,
            trusted_proxy_headers=self.config.trusted_proxy_headers,
            forwarded_proto=request.headers.get("x-forwarded-proto"),
        )
        if not decision.allowed:
            write_auth_log(
                self.config.login_log_path,
                event="insecure_http_rejected",
                user=None,
                src=request.client_ip,
                reason="https_required",
                ts=_utc_now_iso8601(),
            )
            return self._response(decision.status_code, decision.message or "")

        method = request.method.upper()
        if request.path == "/":
            if method != "GET":
                return self._method_not_allowed({"GET"})
            session_record, _ = self._authenticated_session(request)
            if session_record is None:
                return self._redirect("/login")
            return self._response(200, self._render_template("index.html", {"username": session_record.username}), authenticated=True)
        if request.path == "/login":
            if method != "GET":
                return self._method_not_allowed({"GET"})
            return self._response(200, self._render_template("login.html", {}))
        if request.path == "/login/password":
            if method != "POST":
                return self._method_not_allowed({"POST"})
            if not validate_content_type(request.headers.get("content-type"), expected="form"):
                return self._response(415, "Unsupported Media Type")
            return self._handle_login_password(request)
        if request.path == "/login/totp":
            if method == "GET":
                return self._response(200, self._render_template("totp.html", {}))
            if method == "POST":
                if not validate_content_type(request.headers.get("content-type"), expected="form"):
                    return self._response(415, "Unsupported Media Type")
                return self._handle_login_totp(request)
            return self._method_not_allowed({"GET", "POST"})
        if request.path == "/logout":
            if method != "POST":
                return self._method_not_allowed({"POST"})
            return self._handle_logout(request)
        if request.path == "/api/ping":
            if method != "GET":
                return self._method_not_allowed({"GET"})
            session_record, _ = self._authenticated_session(request)
            if session_record is None:
                write_auth_log(self.config.login_log_path, event="api_unauthorized", user=None, src=request.client_ip, reason="missing_session", ts=_utc_now_iso8601())
                return self._response(401, json.dumps({"detail": "Unauthorized"}), content_type="application/json", authenticated=True)
            return self._response(200, json.dumps({"ok": True, "user": session_record.username, "role": session_record.role}), content_type="application/json", authenticated=True)
        if request.path == "/api/echo":
            if method != "POST":
                return self._method_not_allowed({"POST"})
            session_record, csrf_token = self._authenticated_session(request)
            if session_record is None:
                write_auth_log(self.config.login_log_path, event="api_unauthorized", user=None, src=request.client_ip, reason="missing_session", ts=_utc_now_iso8601())
                return self._response(401, json.dumps({"detail": "Unauthorized"}), content_type="application/json", authenticated=True)
            if not self._csrf_valid(request, session_record, csrf_token):
                write_auth_log(self.config.login_log_path, event="csrf_failed", user=session_record.username, src=request.client_ip, reason="invalid_csrf", ts=_utc_now_iso8601())
                return self._response(403, json.dumps({"detail": "CSRF validation failed"}), content_type="application/json", authenticated=True)
            if not validate_content_type(request.headers.get("content-type"), expected="json"):
                return self._response(415, json.dumps({"detail": "Unsupported Media Type"}), content_type="application/json", authenticated=True)
            payload = request.json_body or {}
            if sorted(payload.keys()) != ["message"]:
                return self._response(422, json.dumps({"detail": "Unknown JSON fields"}), content_type="application/json", authenticated=True)
            return self._response(200, json.dumps({"ok": True, "message": str(payload["message"])}), content_type="application/json", authenticated=True)
        return self._response(404, "Not Found")

    def _handle_login_password(self, request: WebRequest) -> WebResponse:
        form = request.form or {}
        username = str(form.get("username") or "")
        password = str(form.get("password") or "")
        try:
            validate_username(username)
        except ValueError:
            pass
        key = attempt_key(username, request.client_ip)
        if self.login_tracker.is_locked(key):
            write_auth_log(self.config.login_log_path, event="lockout", user=username, src=request.client_ip, reason="lockout", ts=_utc_now_iso8601())
            return self._response(429, "Invalid credentials")
        users = load_users(self.config.auth_db_path)
        user = users.get(username)
        if user is None or not user.enabled or not verify_password(password, user.password_hash):
            self.login_tracker.record_failure(key)
            write_auth_log(self.config.login_log_path, event="login_failed", user=username, src=request.client_ip, reason="invalid_credentials", ts=_utc_now_iso8601())
            return self._response(401, "Invalid credentials")

        cookie_value, _ = self.session_store.create(
            username=user.username,
            role=user.role,
            created_at=_utc_now_iso8601(),
            mfa_verified=not self.config.require_totp,
            user_agent_hash=None,
            client_ip_hash=_hash_optional(request.client_ip),
        )
        if self.config.require_totp:
            response = self._redirect("/login/totp")
            response.headers["set-cookie"] = build_set_cookie_header(
                cookie_name=self.config.session_cookie_name,
                cookie_value=cookie_value,
                secure=self._secure_cookie(request),
                max_age_seconds=self.config.session_ttl_minutes * 60,
            )
            return response

        rotated = self.session_store.rotate(cookie_value, created_at=_utc_now_iso8601(), mfa_verified=True)
        final_cookie, final_record = rotated if rotated is not None else (cookie_value, None)
        write_auth_log(self.config.login_log_path, event="login_success", user=username, src=request.client_ip, reason="password_only", ts=_utc_now_iso8601())
        self.login_tracker.clear(key)
        response = self._redirect("/")
        response.headers["set-cookie"] = build_set_cookie_header(
            cookie_name=self.config.session_cookie_name,
            cookie_value=final_cookie,
            secure=self._secure_cookie(request),
            max_age_seconds=self.config.session_ttl_minutes * 60,
        )
        if final_record is not None:
            users[username].last_login_at = final_record.last_seen_at
            write_users(self.config.auth_db_path, users)
        return response

    def _handle_login_totp(self, request: WebRequest) -> WebResponse:
        session_record, cookie_csrf_token = self._session_record(request)
        if session_record is None:
            write_auth_log(self.config.login_log_path, event="totp_failed", user=None, src=request.client_ip, reason="missing_preauth", ts=_utc_now_iso8601())
            return self._response(401, "Invalid credentials")
        form = request.form or {}
        code = str(form.get("totp_code") or "")
        users = load_users(self.config.auth_db_path)
        user = users.get(session_record.username)
        if user is None or user.totp_secret is None:
            write_auth_log(self.config.login_log_path, event="totp_failed", user=session_record.username, src=request.client_ip, reason="invalid_credentials", ts=_utc_now_iso8601())
            return self._response(401, "Invalid credentials")
        try:
            valid = verify_totp_code(user.totp_secret, code)
        except ValueError:
            valid = False
        if not valid:
            write_auth_log(self.config.login_log_path, event="totp_failed", user=session_record.username, src=request.client_ip, reason="invalid_credentials", ts=_utc_now_iso8601())
            return self._response(401, "Invalid credentials")
        current_cookie = self._cookie_value(request)
        rotated = self.session_store.rotate(current_cookie or "", created_at=_utc_now_iso8601(), mfa_verified=True)
        if rotated is None:
            return self._response(401, "Invalid credentials")
        new_cookie, record = rotated
        user.last_login_at = record.last_seen_at
        write_users(self.config.auth_db_path, users)
        write_auth_log(self.config.login_log_path, event="login_success", user=session_record.username, src=request.client_ip, reason="totp_verified", ts=_utc_now_iso8601())
        response = self._redirect("/")
        response.headers["set-cookie"] = build_set_cookie_header(
            cookie_name=self.config.session_cookie_name,
            cookie_value=new_cookie,
            secure=self._secure_cookie(request),
            max_age_seconds=self.config.session_ttl_minutes * 60,
        )
        return response

    def _handle_logout(self, request: WebRequest) -> WebResponse:
        session_record, csrf_token = self._authenticated_session(request)
        if session_record is None:
            return self._response(401, "Unauthorized", authenticated=True)
        if not self._csrf_valid(request, session_record, csrf_token):
            write_auth_log(self.config.login_log_path, event="csrf_failed", user=session_record.username, src=request.client_ip, reason="invalid_csrf", ts=_utc_now_iso8601())
            return self._response(403, "CSRF validation failed", authenticated=True)
        cookie_value = self._cookie_value(request)
        if cookie_value:
            self.session_store.delete(cookie_value)
        write_auth_log(self.config.login_log_path, event="logout", user=session_record.username, src=request.client_ip, reason="logout", ts=_utc_now_iso8601())
        response = self._redirect("/login")
        response.headers["set-cookie"] = build_expire_cookie_header(
            cookie_name=self.config.session_cookie_name,
            secure=self._secure_cookie(request),
        )
        return response

    def _session_record(self, request: WebRequest):
        cookie_value = self._cookie_value(request)
        if cookie_value is None:
            return None, None
        return self.session_store.get(cookie_value)

    def _authenticated_session(self, request: WebRequest):
        record, csrf_token = self._session_record(request)
        if record is None or not record.mfa_verified:
            return None, None
        return record, csrf_token

    def _csrf_valid(self, request: WebRequest, session_record, csrf_token: str | None) -> bool:
        supplied = request.headers.get("x-csrf-token")
        if request.form is not None and "csrf_token" in request.form:
            supplied = str(request.form["csrf_token"])
        if supplied is None or csrf_token is None:
            return False
        return supplied == csrf_token and verify_csrf_token(session_record, csrf_token)

    def _cookie_value(self, request: WebRequest) -> str | None:
        cookies = {} if request.cookies is None else request.cookies
        return cookies.get(self.config.session_cookie_name)

    def _secure_cookie(self, request: WebRequest) -> bool:
        return request.scheme == "https"

    def _method_not_allowed(self, allowed: set[str]) -> WebResponse:
        return WebResponse(405, {"allow": ", ".join(sorted(allowed)), **security_headers(authenticated=False)}, "Method Not Allowed")

    def _response(self, status_code: int, body: str, *, content_type: str = "text/html; charset=utf-8", authenticated: bool = False) -> WebResponse:
        headers = {"content-type": content_type, **security_headers(authenticated=authenticated)}
        return WebResponse(status_code=status_code, headers=headers, body=body)

    def _redirect(self, location: str) -> WebResponse:
        return WebResponse(303, {"location": location, **security_headers(authenticated=False)}, "")

    def _render_template(self, template_name: str, context: dict[str, str]) -> str:
        template_path = Path(__file__).with_name("templates") / template_name
        content = template_path.read_text(encoding="utf-8")
        rendered = content
        for key, value in context.items():
            rendered = rendered.replace("{{ " + key + " }}", value)
        return rendered


def serve_web_panel(
    *,
    config: WebPanelConfig,
    allow_public_bind: bool,
    allow_root_process: bool,
) -> int:
    """Serve the web panel when optional runtime dependencies are present."""
    ensure_bind_allowed(config.bind_host, allow_public_bind=allow_public_bind)
    ensure_not_running_as_root(allow_root_process=allow_root_process)
    try:
        import uvicorn
    except ModuleNotFoundError:
        print('Web panel dependencies are not installed. Install with:\npip install "ScholarOutboundManager[web]"')
        return 1
    ensure_web_storage(config)
    app = _UnsupportedAsgiApp(config)
    uvicorn.run(app, host=config.bind_host, port=config.bind_port)
    return 0


def init_user_from_stdin(
    *,
    username: str,
    password: str,
    auth_db_path: str | Path,
    totp_secret_output_path: str | Path | None = None,
) -> dict[str, str]:
    """Create or replace one web-panel user from stdin password input."""
    user = create_user(username=username, password=password, created_at=_utc_now_iso8601())
    users = load_users(auth_db_path)
    users[user.username] = user
    write_users(auth_db_path, users)
    if totp_secret_output_path is not None:
        output_path = Path(totp_secret_output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(build_otpauth_uri(user.totp_secret or "", user.username), encoding="utf-8")
    return {
        "username": user.username,
        "role": user.role,
        "totp_secret": user.totp_secret or "",
        "otpauth_uri": build_otpauth_uri(user.totp_secret or "", user.username),
    }


class _UnsupportedAsgiApp:
    """Minimal placeholder ASGI app used by uvicorn."""

    def __init__(self, config: WebPanelConfig) -> None:
        self.panel = WebPanelApp(config)

    async def __call__(self, scope, receive, send) -> None:
        del receive
        request = WebRequest(
            method=scope["method"],
            path=scope["path"],
            headers={key.decode("latin-1").lower(): value.decode("latin-1") for key, value in scope.get("headers", [])},
            client_ip=(scope.get("client") or ("127.0.0.1", 0))[0],
            scheme=scope.get("scheme", "http"),
            host=scope.get("server", ("127.0.0.1", 0))[0],
        )
        response = self.panel.handle(request)
        await send({"type": "http.response.start", "status": response.status_code, "headers": [(key.encode("latin-1"), value.encode("latin-1")) for key, value in response.headers.items()]})
        await send({"type": "http.response.body", "body": response.body.encode("utf-8")})


def _hash_optional(value: str | None) -> str | None:
    if value is None:
        return None
    import hashlib

    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _utc_now_iso8601() -> str:
    from datetime import datetime
    from datetime import timezone

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
