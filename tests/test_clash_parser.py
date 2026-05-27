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
    assert candidates[0].supported is True


def test_parse_clash_yaml_subscription_parses_shadowsocks_candidate() -> None:
    """Parse Shadowsocks nodes into candidate models."""
    candidates, _ = parse_clash_yaml_subscription(_ss_yaml(), "fixture-source")

    assert candidates[0].protocol == "shadowsocks"
    assert candidates[0].encryption == "aes-256-gcm"
    assert candidates[0].extra["clash_type"] == "ss"
    assert candidates[0].supported is True


def test_parse_clash_yaml_subscription_preserves_vmess_extra_fields() -> None:
    """Preserve VMess-only fields in candidate.extra."""
    candidates, _ = parse_clash_yaml_subscription(_vmess_yaml(), "fixture-source")

    candidate = candidates[0]
    assert candidate.protocol == "vmess"
    assert candidate.encryption == "auto"
    assert candidate.extra["alter_id"] == 8
    assert candidate.extra["clash_type"] == "vmess"
    assert candidate.supported is True


def test_parse_clash_yaml_subscription_marks_grpc_vless_unsupported() -> None:
    """Keep grpc VLESS unsupported for this phase."""
    candidates, summary = parse_clash_yaml_subscription(_grpc_vless_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].supported is False
    assert "grpc" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_grpc_vmess_unsupported() -> None:
    """Keep grpc VMess unsupported for this phase."""
    candidates, summary = parse_clash_yaml_subscription(_grpc_vmess_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].protocol == "vmess"
    assert candidates[0].supported is False
    assert "grpc" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_parses_hysteria2_candidate() -> None:
    """Parse a conservative Hysteria2 candidate for Xray-backed probing."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_yaml(), "fixture-source")

    assert summary.unsupported_count == 0
    assert candidates[0].protocol == "hysteria2"
    assert candidates[0].supported is True
    assert candidates[0].password == "HY2_PASSWORD_PLACEHOLDER"
    assert candidates[0].server_name == "hy2.example.invalid"
    assert candidates[0].security == "hysteria"
    assert candidates[0].extra["runtime_supported_by"] == ["xray"]
    assert candidates[0].extra["skip_cert_verify"] is True


def test_parse_clash_yaml_subscription_maps_hysteria2_servername_to_server_name() -> None:
    """Accept either Clash sni or servername for Hysteria2 TLS naming."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_servername_yaml(), "fixture-source")

    assert summary.unsupported_count == 0
    assert candidates[0].server_name == "hy2-servername.example.invalid"


def test_parse_clash_yaml_subscription_preserves_hysteria2_skip_cert_verify_false() -> None:
    """Keep explicit false values instead of dropping them."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_skip_verify_false_yaml(), "fixture-source")

    assert summary.unsupported_count == 0
    assert candidates[0].supported is True
    assert "skip_cert_verify" in candidates[0].extra
    assert candidates[0].extra["skip_cert_verify"] is False


def test_parse_clash_yaml_subscription_marks_hysteria2_missing_password_unsupported() -> None:
    """Reject Hysteria2 candidates without password or auth."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_missing_password_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].protocol == "hysteria2"
    assert candidates[0].supported is False
    assert "password/auth" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_hysteria2_missing_server_unsupported() -> None:
    """Reject Hysteria2 candidates without a server."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_missing_server_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert "server" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_hysteria2_missing_port_unsupported() -> None:
    """Reject Hysteria2 candidates without a valid port."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_missing_port_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert "port" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_hysteria2_obfs_unsupported() -> None:
    """Fail closed when Hysteria2 obfs fields are present but unmapped."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_obfs_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].protocol == "hysteria2"
    assert candidates[0].supported is False
    assert candidates[0].extra["obfs"] == "salamander"
    assert candidates[0].extra["obfs-password"] == "OBFS_PASSWORD_PLACEHOLDER"
    assert "obfs is not mapped to Xray yet" in (candidates[0].unsupported_reason or "")


def test_parse_clash_yaml_subscription_marks_hysteria2_alpn_unsupported() -> None:
    """Fail closed when Hysteria2 ALPN is present but not mapped."""
    candidates, summary = parse_clash_yaml_subscription(_hysteria2_alpn_yaml(), "fixture-source")

    assert summary.unsupported_count == 1
    assert candidates[0].protocol == "hysteria2"
    assert candidates[0].supported is False
    assert candidates[0].alpn == "h3,h2"
    assert "alpn is not mapped to Xray yet" in (candidates[0].unsupported_reason or "")


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


def _hysteria2_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Test"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    sni: hy2.example.invalid
    skip-cert-verify: true
    up: "100 Mbps"
    down: "100 Mbps"
""".strip()


def _hysteria2_servername_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Servername"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    servername: hy2-servername.example.invalid
    skip-cert-verify: true
""".strip()


def _hysteria2_skip_verify_false_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Skip Verify False"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    sni: hy2.example.invalid
    skip-cert-verify: false
""".strip()


def _hysteria2_missing_password_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Missing Password"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
""".strip()


def _hysteria2_missing_server_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Missing Server"
    type: hysteria2
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
""".strip()


def _hysteria2_missing_port_yaml() -> str:
    return """
proxies:
  - name: "Hysteria Missing Port"
    type: hysteria2
    server: hy2.example.invalid
    password: HY2_PASSWORD_PLACEHOLDER
""".strip()


def _hysteria2_obfs_yaml() -> str:
    return """
proxies:
  - name: "Hysteria With Obfs"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    obfs: salamander
    obfs-password: OBFS_PASSWORD_PLACEHOLDER
""".strip()


def _hysteria2_alpn_yaml() -> str:
    return """
proxies:
  - name: "Hysteria With ALPN"
    type: hysteria2
    server: hy2.example.invalid
    port: 443
    password: HY2_PASSWORD_PLACEHOLDER
    sni: hy2.example.invalid
    alpn:
      - h3
      - h2
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


def _grpc_vless_yaml() -> str:
    return """
proxies:
  - name: "gRPC VLESS"
    type: vless
    server: example.invalid
    port: 443
    uuid: "00000000-0000-0000-0000-000000000000"
    network: grpc
    tls: true
    servername: www.cloudflare.com
""".strip()


def _grpc_vmess_yaml() -> str:
    return """
proxies:
  - name: "gRPC VMess"
    type: vmess
    server: vmess.example.invalid
    port: 443
    uuid: "00000000-0000-0000-0000-000000000000"
    network: grpc
    cipher: auto
""".strip()
