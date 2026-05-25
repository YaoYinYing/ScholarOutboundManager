"""Tests for configuration loading."""

from pathlib import Path

from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.models import AppConfig


def test_load_example_config_returns_app_config() -> None:
    """Load the example configuration into dataclasses."""
    config_path = Path(__file__).resolve().parent.parent / "config.example.yaml"
    config = load_config(config_path)

    assert isinstance(config, AppConfig)
    assert config.subscriptions[0].name == "third_party_main"
    assert "google-scholar-in" in config.routing.inbound_tags
    assert config.probe.allow_network_probe is False
