"""Configuration helpers for the optional web panel."""

from __future__ import annotations

import json
import os
import secrets
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class WebPanelConfig:
    """Define persisted web-panel configuration."""

    bind_host: str = "127.0.0.1"
    bind_port: int = 8790
    session_secret_path: str = "state_data/web/session_secret"
    auth_db_path: str = "state_data/web/users.json"
    login_log_path: str = "state_data/web/auth.log"
    session_cookie_name: str = "__Host-som_session"
    session_ttl_minutes: int = 30
    absolute_session_ttl_hours: int = 8
    require_totp: bool = True
    allow_insecure_localhost_http: bool = True
    trusted_proxy_headers: bool = False
    failed_login_limit: int = 5
    failed_login_window_seconds: int = 300
    lockout_seconds: int = 900


def load_web_panel_config(path: str | Path) -> WebPanelConfig:
    """Load one JSON-backed web-panel config or return defaults when absent."""
    config_path = Path(path)
    if not config_path.exists():
        return WebPanelConfig()
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Web panel config must be a JSON object.")
    return WebPanelConfig(**{str(key): value for key, value in payload.items()})


def write_web_panel_config(path: str | Path, config: WebPanelConfig) -> None:
    """Persist one web-panel config JSON file."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(asdict(config), indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def ensure_session_secret(path: str | Path) -> str:
    """Generate and persist one CSPRNG session secret when missing."""
    secret_path = Path(path)
    secret_path.parent.mkdir(parents=True, exist_ok=True)
    if secret_path.exists():
        secret = secret_path.read_text(encoding="utf-8").strip()
        if secret:
            _chmod(secret_path, 0o600)
            return secret
    secret = secrets.token_urlsafe(48)
    secret_path.write_text(secret, encoding="utf-8")
    _chmod(secret_path, 0o600)
    return secret


def ensure_web_storage(config: WebPanelConfig) -> None:
    """Create required web-panel storage paths with conservative permissions."""
    _touch_with_mode(Path(config.auth_db_path), "{}\n", 0o600)
    _touch_with_mode(Path(config.login_log_path), "", 0o640)
    ensure_session_secret(config.session_secret_path)


def session_store_path_for(config: WebPanelConfig) -> Path:
    """Resolve the derived session-store path."""
    return Path(config.auth_db_path).with_name("sessions.json")


def _touch_with_mode(path: Path, default_content: str, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        path.write_text(default_content, encoding="utf-8")
    _chmod(path, mode)


def _chmod(path: Path, mode: int) -> None:
    try:
        os.chmod(path, mode)
    except OSError:
        return
