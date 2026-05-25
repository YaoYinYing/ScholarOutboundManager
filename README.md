# ScholarOutboundManager

ScholarOutboundManager is an independent Python project for conservatively generating Google Scholar-specific Xray/XrayR JSON fragments from third-party proxy subscriptions.

## Scope

This project is designed for personal use and intentionally avoids direct system mutation:

- It generates JSON fragments instead of overwriting existing XrayR configuration.
- It does not reload XrayR automatically.
- It does not modify system services automatically.
- It does not commit secrets.
- It redacts sensitive material from normal logs.
- It is intended to fail closed when no Scholar-capable node is available.

## Development Status

The repository is being implemented in phases. Phase 0 only creates the project skeleton, packaging metadata, and configuration template. No network logic is implemented in this phase.

## Planned Layout

```text
ScholarOutboundManager/
  pyproject.toml
  README.md
  config.example.yaml
  scholar_outbound_manager/
    __init__.py
    cli.py
    config.py
    models.py
    fetcher.py
    parsers/
      __init__.py
      base64_subscription.py
      clash_yaml.py
      uri.py
      vless.py
    xray/
      outbound_builder.py
      route_builder.py
      validator.py
    probe/
      scholar_probe.py
      xray_runner.py
      fingerprints.py
    state/
      cache.py
      manifest.py
      history.py
    util/
      redact.py
      logging.py
  tests/
    test_vless_parser.py
    test_outbound_builder.py
    test_scholar_probe_classifier.py
    fixtures/
      vless_reality.txt
      clash_sample.yaml
```

## Usage

Command-line entry points will be added in later phases.
