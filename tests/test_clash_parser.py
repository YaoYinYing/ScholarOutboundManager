"""Tests for Clash YAML subscription parsing."""

from __future__ import annotations

from scholar_outbound_manager.parsers.clash import looks_like_clash_yaml
from scholar_outbound_manager.parsers.clash import parse_clash_yaml_subscription


def test_looks_like_clash_yaml_detects_top_level_proxies_list() -> None:
    """Recognize Clash YAML by its top-level proxies list."""
    assert looks_like_clash_yaml(_vless_reality_yaml()) is True


def test_looks_like_clash_yaml_rejects_yaml_without_proxies() -> None:
    """Reject unrelated YAML mappings."""
    assert looks_like_clash_yaml("proxy-groups:\n  - name: Auto\n") is False


def test_parse_clash_yaml_subscription_parses_vless_reality() -> None:
    """Parse a VLESS Reality Clash node into a candidate."""
    candidates, summary = parse_clash_yaml_subscription(_vless_reality_yaml(), "fixture-source")

    assert summary.proxy_count == 1
    assert summary.parsed_count == 1
    assert summary.unsupported_count == 0
    candidate = candidates[0]
    assert candidate.protocol == "vless"
    assert candidate.raw_name == "Test VLESS Reality"
    assert candidate.security == "reality"
    assert candidate.server_name == "www.cloudflare.com"
    assert candidate.public_key == "PUBLIC_KEY_PLACEHOLDER"
    assert candidate.short_id == "SHORT_ID_PLACEHOLDER"
    assert candidate.fingerprint == "chrome"
    assert candidate.supported is True


def test_parse_clash_yaml_subscription_ignores_proxy_group_url_fields() -> None:
    """Do not treat health-check URLs as candidates."""
    candidates, summary = parse_clash_yaml_subscription(_yaml_with_health_check_url(), "fixture-source")

    assert summary.parsed_count == 1
    assert summary.unsupported_count == 0
    assert summary.ignored_url_field_count >= 1
    assert [candidate.raw_name for candidate in candidates] == ["Test VLESS Reality"]
    assert "http://www.gstatic.com/generate_204" not in str([candidate.to_dict() for candidate in candidates])


def test_health_check_url_does_not_produce_unsupported_url_candidate() -> None:
    """Avoid the previous unsupported-url regression."""
    candidates, _ = parse_clash_yaml_subscription(_yaml_with_health_check_url(), "fixture-source")

    assert all(candidate.raw_name != "unsupported-url" for candidate in candidates)
    assert all(candidate.protocol != "url" for candidate in candidates)


def test_parse_clash_yaml_subscription_parses_trojan_candidate() -> None:
    """Parse Trojan nodes into candidate models."""
    candidates, summary = parse_clash_yaml_subscription(_trojan_yaml(), "fixture-source")

    assert summary.parsed_count == 1
    assert candidates[0].protocol == "trojan"
    assert candidates[0].extra["clash_type"] == "trojan"
    assert candidates[0].supported is False


def test_parse_clash_yaml_subscription_parses_shadowsocks_candidate() -> None:
    """Parse Shadowsocks nodes into candidate models."""
    candidates, _ = parse_clash_yaml_subscription(_ss_yaml(), "fixture-source")

    assert candidates[0].protocol == "shadowsocks"
    assert candidates[0].encryption == "aes-256-gcm"
    assert candidates[0].extra["clash_type"] == "ss"


def test_parse_clash_yaml_subscription_preserves_vmess_extra_fields() -> None:
    """Preserve VMess-only fields in candidate.extra."""
    candidates, _ = parse_clash_yaml_subscription(_vmess_yaml(), "fixture-source")

    candidate = candidates[0]
    assert candidate.protocol == "vmess"
    assert candidate.encryption == "auto"
    assert candidate.extra["alter_id"] == 8
    assert candidate.extra["clash_type"] == "vmess"


def test_parse_clash_yaml_subscription_preserves_unsupported_types() -> None:
    """Keep unsupported Clash proxy types as unsupported candidates."""
    candidates, summary = parse_clash_yaml_subscription(_unsupported_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].protocol == "hysteria2"
    assert candidates[0].supported is False
    assert "not supported yet" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_incomplete_vless_unsupported() -> None:
    """Mark incomplete VLESS entries unsupported instead of dropping them."""
    candidates, summary = parse_clash_yaml_subscription(_invalid_vless_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].supported is False
    assert "Missing required VLESS fields" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_does_not_print(capsys) -> None:
    """Keep the parser side-effect free."""
    parse_clash_yaml_subscription(_vless_reality_yaml(), "fixture-source")
    captured = capsys.readouterr()

    assert captured.out == ""
    assert captured.err == ""


def test_candidate_to_dict_includes_extra_for_clash_candidate() -> None:
    """Include extra metadata in serialized candidates."""
    candidates, _ = parse_clash_yaml_subscription(_vmess_yaml(), "fixture-source")

    assert "extra" in candidates[0].to_dict()


def test_clash_candidates_do_not_synthesize_secret_raw_uri() -> None:
    """Keep raw_uri empty for Clash-derived candidates."""
    candidates, _ = parse_clash_yaml_subscription(_vless_reality_yaml(), "fixture-source")

    assert candidates[0].raw_uri is None


def _vless_reality_yaml() -> str:
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
""".strip()


def _yaml_with_health_check_url() -> str:
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


def _trojan_yaml() -> str:
    return """
proxies:
  - name: "Trojan Test"
    type: trojan
    server: trojan.example.invalid
    port: 443
    password: PASSWORD_PLACEHOLDER
    sni: scholar.example.invalid
    tls: true
    network: ws
    ws-opts:
      path: /ws
      headers:
        Host: cdn.example.invalid
""".strip()


def _ss_yaml() -> str:
    return """
proxies:
  - name: "SS Test"
    type: ss
    server: ss.example.invalid
    port: 8388
    cipher: aes-256-gcm
    password: PASSWORD_PLACEHOLDER
    udp: true
""".strip()


def _vmess_yaml() -> str:
    return """
proxies:
  - name: "VMess Test"
    type: vmess
    server: vmess.example.invalid
    port: 443
    uuid: "00000000-0000-0000-0000-000000000000"
    alterId: 8
    cipher: auto
    tls: true
    network: ws
    ws-opts:
      path: /vmess
      headers:
        Host: edge.example.invalid
""".strip()


def _unsupported_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Test"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
""".strip()


def _invalid_vless_yaml() -> str:
    return """
proxies:
  - name: "Broken VLESS"
    type: vless
    tls: true
    reality-opts:
      public-key: PUBLIC_KEY_PLACEHOLDER
""".strip()
