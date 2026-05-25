"""Schema-oriented tests for the example configuration file."""

from pathlib import Path

import yaml


def test_config_example_contract() -> None:
    """Validate the Phase 0.5 example configuration contract."""
    config_path = Path(__file__).resolve().parent.parent / "config.example.yaml"
    with config_path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle)

    assert isinstance(data["subscriptions"], list)
    assert data["subscriptions"]
    assert isinstance(data["subscriptions"][0], dict)
    assert "inbound_tags" in data["routing"]
    assert data["routing"]["inbound_tags"]
    assert data["probe"]["allow_network_probe"] is False
    assert data["generation"]["tag_prefix"] == "google-scholar-node-"
