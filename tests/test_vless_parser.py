"""Import smoke tests for the VLESS parser module."""

from scholar_outbound_manager.parsers import vless


def test_vless_module_imports() -> None:
    """Import the VLESS parser module successfully."""
    assert vless is not None
