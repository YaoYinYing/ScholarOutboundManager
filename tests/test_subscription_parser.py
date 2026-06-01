"""Tests for subscription text decoding and candidate parsing."""

from __future__ import annotations

import base64

import pytest

from scholar_outbound_manager.fetcher import FetchedSubscription
from scholar_outbound_manager.parsers.subscription import decode_subscription_text
from scholar_outbound_manager.parsers.subscription import extract_proxy_uris
from scholar_outbound_manager.parsers.subscription import parse_fetched_subscriptions
from scholar_outbound_manager.parsers.subscription import parse_subscription_content


def test_decode_subscription_text_keeps_plain_text() -> None:
    """Return plain text unchanged in plain mode."""
    raw_text = "vless://plain-text-line"

    assert decode_subscription_text(raw_text, fmt="plain") == raw_text


def test_decode_subscription_text_supports_explicit_base64() -> None:
    """Decode explicit base64 subscription text."""
    raw_text = base64.b64encode(b"vless://base64-line").decode("ascii")

    assert decode_subscription_text(raw_text, fmt="base64") == "vless://base64-line"


def test_decode_subscription_text_auto_detects_plain_uris() -> None:
    """Keep direct URI content unchanged in auto mode."""
    raw_text = "vless://plain-auto"

    assert decode_subscription_text(raw_text, fmt="auto") == raw_text


def test_decode_subscription_text_auto_detects_base64_uris() -> None:
    """Decode base64 when auto mode finds URI content after decoding."""
    raw_text = base64.b64encode(b"vless://auto-base64").decode("ascii")

    assert decode_subscription_text(raw_text, fmt="auto") == "vless://auto-base64"


def test_decode_subscription_text_rejects_invalid_explicit_base64() -> None:
    """Raise when explicit base64 decoding fails."""
    with pytest.raises(ValueError, match="base64"):
        decode_subscription_text("not valid base64!!", fmt="base64")


def test_extract_proxy_uris_ignores_empty_and_comment_lines() -> None:
    """Keep only URI-bearing non-comment lines."""
    text = "\n# comment\nvless://one\n\n  # another comment\nvmess://two  \nplain\n"

    assert extract_proxy_uris(text) == ["vless://one", "vmess://two"]


def test_parse_subscription_content_supports_vless_candidates() -> None:
    """Parse supported VLESS candidates from decoded subscription text."""
    parsed = parse_subscription_content(
        "vless://00000000-0000-0000-0000-000000000000@example.invalid:443?security=reality&pbk=PUBLIC_KEY_PLACEHOLDER&sni=www.cloudflare.com#US%20Scholar",
        source_name="fixture-source",
    )

    assert parsed.parsed_count == 1
    assert parsed.unsupported_count == 0
    assert parsed.candidates[0].protocol == "vless"
    assert parsed.candidates[0].supported is True
    assert parsed.parser_kind == "uri_lines"


def test_parse_subscription_content_preserves_unsupported_non_vless_candidates() -> None:
    """Keep unsupported non-VLESS URI lines as candidate records."""
    parsed = parse_subscription_content(
        "vmess://example.invalid:443#unsupported-node",
        source_name="fixture-source",
    )

    assert parsed.parsed_count == 1
    assert parsed.unsupported_count == 1
    assert parsed.candidates[0].supported is False
    assert parsed.candidates[0].protocol == "vmess"


def test_parse_subscription_content_counts_unsupported_candidates() -> None:
    """Count unsupported candidates across a mixed subscription body."""
    parsed = parse_subscription_content(
        "\n".join(
            [
                "vless://00000000-0000-0000-0000-000000000000@example.invalid:443?security=reality&pbk=PUBLIC_KEY_PLACEHOLDER&sni=www.cloudflare.com#ok",
                "vmess://example.invalid:443#bad",
            ]
        ),
        source_name="fixture-source",
    )

    assert parsed.parsed_count == 2
    assert parsed.unsupported_count == 1


def test_parse_fetched_subscriptions_uses_format_map() -> None:
    """Parse fetched subscriptions with per-source format selection."""
    encoded = base64.b64encode(
        b"vless://00000000-0000-0000-0000-000000000000@example.invalid:443?security=reality&pbk=PUBLIC_KEY_PLACEHOLDER&sni=www.cloudflare.com#node"
    ).decode("ascii")
    fetched = [FetchedSubscription(source_name="fixture-source", content=encoded, byte_count=len(encoded))]

    parsed = parse_fetched_subscriptions(fetched, {"fixture-source": "base64"})

    assert len(parsed) == 1
    assert parsed[0].parsed_count == 1
    assert parsed[0].candidates[0].supported is True


def test_parse_subscription_content_keeps_hysteria2_unsupported_by_default() -> None:
    """Default parsing should not admit experimental Hysteria2 into the supported pool."""
    parsed = parse_subscription_content(_clash_hysteria2_yaml(), source_name="fixture-source")

    assert parsed.parser_kind == "clash_yaml"
    assert parsed.parsed_count == 1
    assert parsed.unsupported_count == 1
    assert parsed.candidates[0].protocol == "hysteria2"
    assert parsed.candidates[0].supported is False


def test_parse_fetched_subscriptions_can_enable_experimental_hysteria2() -> None:
    """Fetch parsing should support an explicit experimental opt-in."""
    fetched = [FetchedSubscription(source_name="fixture-source", content=_clash_hysteria2_yaml(), byte_count=64)]

    parsed = parse_fetched_subscriptions(
        fetched,
        {"fixture-source": "auto"},
        enable_experimental_hysteria2=True,
    )

    assert len(parsed) == 1
    assert parsed[0].unsupported_count == 0
    assert parsed[0].candidates[0].supported is True


def test_parse_subscription_content_uses_clash_parser_for_clash_yaml() -> None:
    """Detect Clash YAML and parse only the top-level proxies list."""
    parsed = parse_subscription_content(_clash_yaml_with_health_check(), source_name="fixture-source")

    assert parsed.parser_kind == "clash_yaml"
    assert parsed.parsed_count == 1
    assert parsed.unsupported_count == 0
    assert parsed.candidates[0].raw_name == "Test VLESS Reality"


def test_parse_subscription_content_does_not_parse_health_check_url_as_uri() -> None:
    """Avoid turning proxy-group health-check URLs into unsupported candidates."""
    parsed = parse_subscription_content(_clash_yaml_with_health_check(), source_name="fixture-source")

    assert all(candidate.protocol != "url" for candidate in parsed.candidates)
    assert all(candidate.raw_name != "unsupported-url" for candidate in parsed.candidates)


def test_parse_subscription_content_still_supports_plain_uri_subscriptions() -> None:
    """Keep the original URI-line fallback behavior."""
    parsed = parse_subscription_content("vmess://example.invalid:443#unsupported-node", source_name="fixture-source")

    assert parsed.parser_kind == "uri_lines"
    assert parsed.parsed_count == 1
    assert parsed.candidates[0].protocol == "vmess"


def test_parse_subscription_content_decodes_base64_wrapped_clash_yaml() -> None:
    """Support auto-decoding for base64-wrapped Clash YAML payloads."""
    encoded = base64.b64encode(_clash_yaml_with_health_check().encode("utf-8")).decode("ascii")

    parsed = parse_subscription_content(encoded, source_name="fixture-source")

    assert parsed.parser_kind == "clash_yaml"
    assert parsed.parsed_count == 1
    assert parsed.candidates[0].protocol == "vless"


def test_parse_subscription_content_falls_back_to_uri_lines_for_invalid_yaml() -> None:
    """Do not let invalid YAML block the legacy URI-line parser."""
    content = "proxies: [\nvless://example.invalid:443#not-yaml"

    parsed = parse_subscription_content(content, source_name="fixture-source")

    assert parsed.parser_kind == "uri_lines"
    assert parsed.parsed_count == 1
    assert parsed.candidates[0].protocol == "vless"


def _clash_yaml_with_health_check() -> str:
    return """
proxies:
  - name: "Test VLESS Reality"
    type: vless
    server: example.invalid
    port: 443
    uuid: "00000000-0000-0000-0000-000000000000"
    network: tcp
    tls: true
    reality-opts:
      public-key: PUBLIC_KEY_PLACEHOLDER
      short-id: SHORT_ID_PLACEHOLDER
    servername: www.cloudflare.com
    client-fingerprint: chrome
proxy-groups:
  - name: Auto
    type: url-test
    proxies:
      - Test VLESS Reality
    url: http://www.gstatic.com/generate_204
    interval: 300
""".strip()


def _clash_hysteria2_yaml() -> str:
    return """
proxies:
  - name: US HY2
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    sni: hy2.example.invalid
    skip-cert-verify: true
""".strip()
