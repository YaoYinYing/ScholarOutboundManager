"""Public Xray outbound helpers backed by spec-builder and renderer layers."""

from __future__ import annotations

from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.xray.renderer import render_xray_outbound
from scholar_outbound_manager.xray.spec_builder import build_hysteria2_spec
from scholar_outbound_manager.xray.spec_builder import build_shadowsocks_spec
from scholar_outbound_manager.xray.spec_builder import build_trojan_spec
from scholar_outbound_manager.xray.spec_builder import build_vless_spec
from scholar_outbound_manager.xray.spec_builder import build_vmess_spec
from scholar_outbound_manager.xray.spec_builder import build_xray_outbound_spec


def build_xray_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray outbound for a supported candidate protocol."""
    return render_xray_outbound(build_xray_outbound_spec(candidate, tag))


def build_vless_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray VLESS outbound fragment from a parsed candidate."""
    return render_xray_outbound(build_vless_spec(candidate, tag))


def build_trojan_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Trojan outbound fragment."""
    return render_xray_outbound(build_trojan_spec(candidate, tag))


def build_shadowsocks_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Shadowsocks outbound fragment."""
    return render_xray_outbound(build_shadowsocks_spec(candidate, tag))


def build_vmess_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray VMess outbound fragment."""
    return render_xray_outbound(build_vmess_spec(candidate, tag))


def build_hysteria2_outbound(candidate: CandidateProxy, tag: str) -> dict[str, object]:
    """Build one Xray Hysteria outbound fragment for a Hysteria2 candidate."""
    return render_xray_outbound(build_hysteria2_spec(candidate, tag))
