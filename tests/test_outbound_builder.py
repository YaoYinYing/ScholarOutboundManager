"""Import smoke tests for the outbound builder module."""

from scholar_outbound_manager.xray import outbound_builder


def test_outbound_builder_module_imports() -> None:
    """Import the outbound builder module successfully."""
    assert outbound_builder is not None
