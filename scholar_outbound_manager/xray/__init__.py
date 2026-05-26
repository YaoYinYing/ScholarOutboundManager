"""Helpers for generating Xray JSON fragments."""

from scholar_outbound_manager.xray.outbound_builder import build_xray_outbound
from scholar_outbound_manager.xray.outbound_builder import build_vless_outbound
from scholar_outbound_manager.xray.route_builder import build_dedicated_inbound_routes

__all__ = [
    "build_dedicated_inbound_routes",
    "build_xray_outbound",
    "build_vless_outbound",
]
