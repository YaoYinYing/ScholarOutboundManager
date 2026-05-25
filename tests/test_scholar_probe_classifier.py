"""Import smoke tests for the Scholar probe module."""

from scholar_outbound_manager.probe import scholar_probe


def test_scholar_probe_module_imports() -> None:
    """Import the Scholar probe module successfully."""
    assert scholar_probe is not None
