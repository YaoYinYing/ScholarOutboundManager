"""Opaque cookie-session helpers for the optional web panel."""

from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class SessionRecord:
    """Represent one server-side session record."""

    session_id_hash: str
    username: str
    role: str
    created_at: str
    last_seen_at: str
    mfa_verified: bool
    csrf_token_hash: str
    user_agent_hash: str | None = None
    client_ip_hash: str | None = None


class SessionStore:
    """Persist opaque sessions in a local JSON file."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    def load(self) -> dict[str, SessionRecord]:
        if not self.path.exists():
            return {}
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            raise ValueError("session store must be a JSON object.")
        records: dict[str, SessionRecord] = {}
        for key, value in payload.items():
            if isinstance(value, dict):
                records[str(key)] = SessionRecord(**{str(child_key): child_value for child_key, child_value in value.items()})
        return records

    def save(self, records: dict[str, SessionRecord]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {key: asdict(value) for key, value in records.items()}
        self.path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, sort_keys=True), encoding="utf-8")

    def create(
        self,
        *,
        username: str,
        role: str,
        created_at: str,
        mfa_verified: bool,
        user_agent_hash: str | None = None,
        client_ip_hash: str | None = None,
    ) -> tuple[str, SessionRecord]:
        session_id = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(24)
        record = SessionRecord(
            session_id_hash=_hash_value(session_id),
            username=username,
            role=role,
            created_at=created_at,
            last_seen_at=created_at,
            mfa_verified=mfa_verified,
            csrf_token_hash=_hash_value(csrf_token),
            user_agent_hash=user_agent_hash,
            client_ip_hash=client_ip_hash,
        )
        records = self.load()
        records[record.session_id_hash] = record
        self.save(records)
        return session_id + "." + csrf_token, record

    def get(self, cookie_value: str) -> tuple[SessionRecord | None, str | None]:
        session_id, csrf_token = split_cookie_value(cookie_value)
        if session_id is None or csrf_token is None:
            return None, None
        record = self.load().get(_hash_value(session_id))
        return record, csrf_token

    def delete(self, cookie_value: str) -> None:
        session_id, _ = split_cookie_value(cookie_value)
        if session_id is None:
            return
        records = self.load()
        records.pop(_hash_value(session_id), None)
        self.save(records)

    def rotate(
        self,
        cookie_value: str,
        *,
        created_at: str,
        mfa_verified: bool,
    ) -> tuple[str, SessionRecord] | None:
        record, _ = self.get(cookie_value)
        if record is None:
            return None
        self.delete(cookie_value)
        return self.create(
            username=record.username,
            role=record.role,
            created_at=created_at,
            mfa_verified=mfa_verified,
            user_agent_hash=record.user_agent_hash,
            client_ip_hash=record.client_ip_hash,
        )


def build_set_cookie_header(
    *,
    cookie_name: str,
    cookie_value: str,
    secure: bool,
    max_age_seconds: int,
) -> str:
    """Build one session Set-Cookie header value."""
    parts = [
        f"{cookie_name}={cookie_value}",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        f"Max-Age={max_age_seconds}",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def build_expire_cookie_header(
    *,
    cookie_name: str,
    secure: bool,
) -> str:
    """Build one logout cookie-expiry header value."""
    parts = [
        f"{cookie_name}=",
        "Path=/",
        "HttpOnly",
        "SameSite=Strict",
        "Max-Age=0",
    ]
    if secure:
        parts.append("Secure")
    return "; ".join(parts)


def split_cookie_value(cookie_value: str | None) -> tuple[str | None, str | None]:
    """Split the opaque cookie payload into session and csrf components."""
    if not cookie_value or "." not in cookie_value:
        return None, None
    session_id, csrf_token = cookie_value.split(".", 1)
    if not session_id or not csrf_token:
        return None, None
    return session_id, csrf_token


def verify_csrf_token(record: SessionRecord, csrf_token: str) -> bool:
    """Verify one supplied CSRF token."""
    return _hash_value(csrf_token) == record.csrf_token_hash


def _hash_value(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()
