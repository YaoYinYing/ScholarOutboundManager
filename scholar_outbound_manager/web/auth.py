"""User, password, TOTP, and login-throttling helpers for the optional web panel."""

from __future__ import annotations

import base64
import binascii
import hashlib
import hmac
import json
import re
import secrets
import struct
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from passlib.exc import MissingBackendError
from passlib.hash import argon2


USERNAME_PATTERN = re.compile(r"^[a-zA-Z][a-zA-Z0-9_.-]{2,31}$")
ALLOWED_ROLES = {"viewer", "operator", "admin"}


@dataclass(slots=True)
class WebUser:
    """Represent one web-panel user."""

    username: str
    password_hash: str
    totp_secret: str | None
    role: str = "admin"
    enabled: bool = True
    created_at: str = ""
    last_login_at: str | None = None


class LoginAttemptTracker:
    """Track failed login attempts by username/IP hash."""

    def __init__(self, *, limit: int, window_seconds: int, lockout_seconds: int) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self.lockout_seconds = lockout_seconds
        self._attempts: dict[str, list[float]] = {}
        self._lockouts: dict[str, float] = {}

    def is_locked(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        locked_until = self._lockouts.get(key)
        return locked_until is not None and locked_until > current

    def record_failure(self, key: str, *, now: float | None = None) -> bool:
        current = time.time() if now is None else now
        attempts = [stamp for stamp in self._attempts.get(key, []) if current - stamp <= self.window_seconds]
        attempts.append(current)
        self._attempts[key] = attempts
        if len(attempts) >= self.limit:
            self._lockouts[key] = current + self.lockout_seconds
            return True
        return False

    def clear(self, key: str) -> None:
        self._attempts.pop(key, None)
        self._lockouts.pop(key, None)


def validate_username(username: str) -> None:
    """Validate web-panel usernames."""
    if username == "root":
        raise ValueError("username root is forbidden.")
    if not USERNAME_PATTERN.fullmatch(username):
        raise ValueError("username must match ^[a-zA-Z][a-zA-Z0-9_.-]{2,31}$.")


def validate_role(role: str) -> None:
    """Validate web-panel roles."""
    if role == "root":
        raise ValueError("role root is forbidden.")
    if role not in ALLOWED_ROLES:
        raise ValueError(f"role must be one of {sorted(ALLOWED_ROLES)}.")


def hash_password(password: str) -> str:
    """Hash one password with Argon2."""
    if not password:
        raise ValueError("password must not be empty.")
    try:
        return argon2.hash(password)
    except MissingBackendError:
        return _pbkdf2_hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    """Verify one password against its Argon2 hash."""
    if password_hash.startswith("pbkdf2_sha256$"):
        return _pbkdf2_verify(password, password_hash)
    try:
        return bool(argon2.verify(password, password_hash))
    except Exception:
        return False


def generate_totp_secret() -> str:
    """Generate one base32 TOTP secret."""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def build_otpauth_uri(secret: str, username: str, issuer: str = "ScholarOutboundManager") -> str:
    """Build a standard otpauth URI for provisioning."""
    return f"otpauth://totp/{issuer}:{username}?secret={secret}&issuer={issuer}"


def validate_totp_code(code: str) -> None:
    """Validate TOTP input format."""
    if not re.fullmatch(r"\d{6}", code):
        raise ValueError("TOTP code must be exactly 6 digits.")


def verify_totp_code(secret: str, code: str, *, for_time: int | None = None, valid_window: int = 1) -> bool:
    """Verify one TOTP code with a small drift window."""
    validate_totp_code(code)
    current = int(time.time()) if for_time is None else int(for_time)
    for offset in range(-valid_window, valid_window + 1):
        if _totp_at(secret, current + offset * 30) == code:
            return True
    return False


def create_user(
    *,
    username: str,
    password: str,
    created_at: str,
    role: str = "admin",
) -> WebUser:
    """Create one validated web user."""
    validate_username(username)
    validate_role(role)
    return WebUser(
        username=username,
        password_hash=hash_password(password),
        totp_secret=generate_totp_secret(),
        role=role,
        enabled=True,
        created_at=created_at,
        last_login_at=None,
    )


def load_users(path: str | Path) -> dict[str, WebUser]:
    """Load one username-keyed user database."""
    db_path = Path(path)
    if not db_path.exists():
        return {}
    payload = json.loads(db_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("auth DB must be a JSON object keyed by username.")
    users: dict[str, WebUser] = {}
    for key, value in payload.items():
        if isinstance(value, dict):
            users[str(key)] = WebUser(**{str(child_key): child_value for child_key, child_value in value.items()})
    return users


def write_users(path: str | Path, users: dict[str, WebUser]) -> None:
    """Persist one username-keyed user database."""
    db_path = Path(path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {username: asdict(user) for username, user in users.items()}
    db_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")


def attempt_key(username: str, client_ip: str) -> str:
    """Build one irreversible login-attempt key."""
    material = f"{username}|{client_ip}".encode("utf-8")
    return hashlib.sha256(material).hexdigest()


def _totp_at(secret: str, for_time: int, *, digits: int = 6, step: int = 30) -> str:
    normalized = secret.upper()
    padding = "=" * ((8 - len(normalized) % 8) % 8)
    key = base64.b32decode(normalized + padding)
    counter = int(for_time // step)
    digest = hmac.new(key, struct.pack(">Q", counter), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    code = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def _pbkdf2_hash(password: str, *, rounds: int = 200_000) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return "pbkdf2_sha256${}${}${}".format(
        rounds,
        binascii.hexlify(salt).decode("ascii"),
        binascii.hexlify(derived).decode("ascii"),
    )


def _pbkdf2_verify(password: str, password_hash: str) -> bool:
    try:
        _, rounds_text, salt_hex, digest_hex = password_hash.split("$", 3)
        rounds = int(rounds_text)
        salt = binascii.unhexlify(salt_hex.encode("ascii"))
        expected = binascii.unhexlify(digest_hex.encode("ascii"))
    except (ValueError, binascii.Error):
        return False
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, rounds)
    return hmac.compare_digest(derived, expected)
