"""Tests for sensitive value redaction helpers."""

from scholar_outbound_manager.util.redact import redact_mapping
from scholar_outbound_manager.util.redact import redact_text


def test_redact_mapping_hides_sensitive_fields() -> None:
    """Redact declared sensitive mapping fields."""
    value = {
        "url": "https://example.invalid/path?token=secret-value",
        "uuid": "12345678-1234-1234-1234-1234567890ab",
        "short_id": "abcdef123456",
        "headers": {"Authorization": "Bearer secret-token"},
        "protocol": "vless",
        "address": "example.invalid",
        "port": 443,
        "raw_name": "sample-node",
    }

    result = redact_mapping(value)

    assert result["url"] == "https://example.invalid/path<REDACTED_QUERY>"
    assert result["uuid"] == "1234<REDACTED>90ab"
    assert result["short_id"] == "abcd<REDACTED>3456"
    assert result["headers"]["Authorization"] == "Bear<REDACTED>oken"
    assert result["protocol"] == "vless"
    assert result["address"] == "example.invalid"
    assert result["port"] == 443
    assert result["raw_name"] == "sample-node"


def test_redact_text_hides_short_secrets() -> None:
    """Redact short sensitive strings without partial exposure."""
    assert redact_text("secret") == "<REDACTED>"


def test_redact_ipv6_url_preserves_brackets_and_port() -> None:
    """Redact IPv6 URLs without breaking the authority syntax."""
    value = "https://[::1]:8443/path?token=abc"

    assert redact_text(value) == "https://[::1]:8443/path<REDACTED_QUERY>"


def test_redact_mapping_hides_hysteria2_secret_fields() -> None:
    """Redact Hysteria2-related auth and obfs fields, including nested mappings."""
    value = {
        "extra": {
            "auth": "HY2_PASSWORD_PLACEHOLDER",
            "obfs-password": "OBFS_PASSWORD_PLACEHOLDER",
            "sni": "hy2.example.invalid",
        },
        "items": [
            {
                "auth": "ANOTHER_SECRET",
            }
        ],
    }

    result = redact_mapping(value)

    assert result["extra"]["auth"] == "HY2_<REDACTED>LDER"
    assert result["extra"]["obfs-password"] == "OBFS<REDACTED>LDER"
    assert result["extra"]["sni"] == "hy2.<REDACTED>alid"
    assert result["items"][0]["auth"] == "ANOT<REDACTED>CRET"
