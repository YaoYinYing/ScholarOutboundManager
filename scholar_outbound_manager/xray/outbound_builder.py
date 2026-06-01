"""Backward-compatible import shim for Xray outbound helpers."""

from scholar_outbound_manager.xray.outbound import build_hysteria2_outbound
from scholar_outbound_manager.xray.outbound import build_shadowsocks_outbound
from scholar_outbound_manager.xray.outbound import build_trojan_outbound
from scholar_outbound_manager.xray.outbound import build_vless_outbound
from scholar_outbound_manager.xray.outbound import build_vmess_outbound
from scholar_outbound_manager.xray.outbound import build_xray_outbound

__all__ = [
    "build_hysteria2_outbound",
    "build_shadowsocks_outbound",
    "build_trojan_outbound",
    "build_vless_outbound",
    "build_vmess_outbound",
    "build_xray_outbound",
]
