"""Tests for VLESS URI parsing."""

from pathlib import Path

from scholar_outbound_manager.parsers.uri import parse_proxy_uri
from scholar_outbound_manager.parsers.vless import parse_vless_uri


def test_parse_vless_reality_uri() -> None:
    """Parse a VLESS Reality URI into the expected candidate fields."""
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "vless_reality.txt"
    uri = fixture_path.read_text(encoding="utf-8").strip()

    candidate = parse_vless_uri(uri, source_name="fixture-source")

    assert candidate.address == "example.invalid"
    assert candidate.port == 443
    assert candidate.user_id == "00000000-0000-0000-0000-000000000000"
    assert candidate.flow == "xtls-rprx-vision"
    assert candidate.server_name == "www.apple.com.cn"
    assert candidate.fingerprint == "chrome"
    assert candidate.public_key == "PUBLIC_KEY_PLACEHOLDER"
    assert candidate.short_id == "SHORT_ID_PLACEHOLDER"
    assert candidate.raw_name == "US Scholar IPv4"
    assert candidate.protocol == "vless"
    assert candidate.encryption == "none"
    assert candidate.supported is True


def test_parse_vless_uri_without_port_is_unsupported() -> None:
    """Mark a VLESS URI without a port as unsupported."""
    uri = (
        "vless://00000000-0000-0000-0000-000000000000@example.invalid"
        "?type=tcp&security=reality&sni=www.apple.com.cn&pbk=PUBLIC_KEY#NoPort"
    )

    candidate = parse_vless_uri(uri, source_name="fixture-source")

    assert candidate.supported is False
    assert candidate.port == 0
    assert "port" in (candidate.unsupported_reason or "")


def test_parse_proxy_uri_marks_invalid_scheme_as_unsupported() -> None:
    """Mark unsupported URI schemes consistently."""
    candidate = parse_proxy_uri("vmess://example.invalid", source_name="fixture-source")

    assert candidate.supported is False
    assert "Unsupported proxy scheme" in (candidate.unsupported_reason or "")


def test_parse_vless_uri_decodes_raw_name() -> None:
    """Decode the URI fragment for the display name."""
    uri = (
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:443"
        "?type=tcp#US%20Scholar%20IPv4"
    )

    candidate = parse_vless_uri(uri, source_name="fixture-source")

    assert candidate.raw_name == "US Scholar IPv4"


def test_parse_vless_uri_without_fragment_uses_safe_name() -> None:
    """Avoid exposing credentials when the URI has no fragment."""
    uri = "vless://00000000-0000-0000-0000-000000000000@example.invalid:443?type=tcp"

    candidate = parse_vless_uri(uri, source_name="fixture-source")

    assert candidate.raw_name == "unnamed-vless-example.invalid"
    assert "00000000-0000-0000-0000-000000000000" not in candidate.raw_name


def test_parse_vless_uri_with_invalid_port_is_unsupported_without_exception() -> None:
    """Handle an invalid VLESS port without raising."""
    uri = (
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:notaport"
        "?type=tcp#BadPort"
    )

    candidate = parse_vless_uri(uri, source_name="fixture-source")

    assert candidate.supported is False
    assert "invalid port" in (candidate.unsupported_reason or "").lower()


def test_parse_proxy_uri_unsupported_scheme_does_not_leak_credentials() -> None:
    """Keep raw names safe for unsupported schemes."""
    candidate = parse_proxy_uri(
        "trojan://password@example.invalid:443#TrojanNode",
        source_name="fixture-source",
    )

    assert candidate.raw_name == "TrojanNode"

    candidate_without_fragment = parse_proxy_uri(
        "trojan://password@example.invalid:443",
        source_name="fixture-source",
    )
    assert candidate_without_fragment.raw_name == "unsupported-trojan"
    assert "password" not in candidate_without_fragment.raw_name


def test_parse_proxy_uri_unsupported_scheme_decodes_fragment() -> None:
    """Decode unsupported-scheme fragments without exposing credentials."""
    candidate = parse_proxy_uri(
        "trojan://password@example.invalid:443#US%20Node",
        source_name="fixture-source",
    )

    assert candidate.raw_name == "US Node"
    assert "password" not in candidate.raw_name
