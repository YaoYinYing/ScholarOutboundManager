"""Tests for select CLI commands."""

from __future__ import annotations

import json
from pathlib import Path

from scholar_outbound_manager import cli


def test_select_list_outputs_redacted_table(tmp_path: Path, capsys) -> None:
    """Render the default redacted table without secrets."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(["select", "list", "--candidates", str(candidates_path)])
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "candidate_id" in captured.out
    assert "candidate-001" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_select_list_json_outputs_redacted_catalog(tmp_path: Path, capsys) -> None:
    """Render the catalog as redacted JSON."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(["select", "list", "--candidates", str(candidates_path), "--json"])
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload[0]["candidate_id"] == "candidate-001"
    assert "address" not in payload[0]
    _assert_no_secrets(captured.out + captured.err)


def test_select_choose_by_candidate_id_writes_sensitive_artifact(tmp_path: Path, capsys) -> None:
    """Write one selected-candidate artifact without printing secrets."""
    candidates_path = _write_passed_candidates(tmp_path)
    output_path = tmp_path / "selected_candidate.json"

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--candidate-id",
            "candidate-001",
            "--output",
            str(output_path),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    artifact = json.loads(output_path.read_text(encoding="utf-8"))
    assert artifact["sensitive"] is True
    assert artifact["selected_candidate_id"] == "candidate-001"
    assert artifact["candidate"]["address"] == "example.invalid"
    assert "selected_candidate_id: candidate-001" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_select_choose_strategy_auto_with_manual_candidate_id(tmp_path: Path, capsys) -> None:
    """Keep manual candidate-id priority even under auto strategy."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "auto",
            "--candidate-id",
            "candidate-001",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selection_method: manual:candidate_id" in captured.out


def test_select_choose_strategy_geo_nearest_with_cache(tmp_path: Path, capsys) -> None:
    """Choose the nearest candidate from local geo cache."""
    candidates_path = _write_passed_candidates(tmp_path)
    _write_geo_files(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "geo_nearest",
            "--host-geo",
            str(tmp_path / "host_geo.json"),
            "--geo-cache",
            str(tmp_path / "candidate_geo_cache.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selection_method: geo_nearest" in captured.out
    assert "geo_distance_km:" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_select_choose_strategy_first(tmp_path: Path, capsys) -> None:
    """Allow explicit first-candidate fallback strategy."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "first",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selection_method: first" in captured.out


def test_select_choose_missing_geo_cache_falls_back_when_allowed(tmp_path: Path, capsys) -> None:
    """Fall back to first when geo cache is unavailable."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "geo_nearest",
            "--host-geo",
            str(tmp_path / "missing_host.json"),
            "--geo-cache",
            str(tmp_path / "missing_cache.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selection_method: fallback:first" in captured.out
    _assert_no_secrets(captured.out + captured.err)


def test_select_explain_outputs_redacted_explanation(tmp_path: Path, capsys) -> None:
    """Explain selection ordering without writing artifacts or leaking secrets."""
    candidates_path = _write_passed_candidates(tmp_path)
    _write_geo_files(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "explain",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "geo_nearest",
            "--host-geo",
            str(tmp_path / "host_geo.json"),
            "--geo-cache",
            str(tmp_path / "candidate_geo_cache.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    payload = json.loads(captured.out)
    assert payload["decision"]["method"] == "geo_nearest"
    assert "geo_distance_km" in payload["catalog"][0]
    _assert_no_secrets(captured.out + captured.err)


def test_select_choose_requires_exactly_one_selector(tmp_path: Path, capsys) -> None:
    """Reject conflicting candidate selection args."""
    candidates_path = _write_passed_candidates(tmp_path)

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--candidate-id",
            "candidate-001",
            "--candidate-index",
            "0",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 1
    assert "mutually exclusive" in captured.err


def _write_passed_candidates(tmp_path: Path) -> Path:
    path = tmp_path / "passed_candidates.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "security": "reality",
                            "server_name": "www.cloudflare.com",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "password": "PASSWORD_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    },
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node-b",
                            "protocol": "trojan",
                            "address": "example-b.invalid",
                            "port": 443,
                            "password": "PASSWORD_PLACEHOLDER",
                            "security": "tls",
                            "server_name": "www.cloudflare.com",
                            "supported": True,
                        },
                        "probe": {
                            "candidate_id": "candidate-002",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 12,
                            "checked_at": "2026-05-27T00:00:00Z",
                            "passed": True,
                        },
                    },
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _write_geo_files(tmp_path: Path) -> None:
    (tmp_path / "host_geo.json").write_text(
        json.dumps(
            {
                "country": "TW",
                "region": "Taipei",
                "city": "Taipei",
                "latitude": 25.033,
                "longitude": 121.565,
                "accuracy_radius_km": 50,
                "source": "manual",
                "updated_at": "2026-05-27T00:00:00Z",
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "candidate_geo_cache.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "records": [
                    {
                        "candidate_id": "candidate-001",
                        "protocol": "vless",
                        "geo": {
                            "country": "TW",
                            "city": "Taipei",
                            "latitude": 25.0375,
                            "longitude": 121.5637,
                            "accuracy_radius_km": 20,
                            "source": "manual",
                            "updated_at": "2026-05-27T00:00:00Z",
                        },
                        "confidence": "city",
                        "note": "cached",
                    },
                    {
                        "candidate_id": "candidate-002",
                        "protocol": "trojan",
                        "geo": {
                            "country": "JP",
                            "city": "Tokyo",
                            "latitude": 35.6762,
                            "longitude": 139.6503,
                            "accuracy_radius_km": 100,
                            "source": "manual",
                            "updated_at": "2026-05-27T00:00:00Z",
                        },
                        "confidence": "city",
                        "note": "cached",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _assert_no_secrets(rendered: str) -> None:
    lowered = rendered.lower()
    assert "raw_uri" not in lowered
    assert "00000000-0000-0000-0000-000000000000" not in lowered
    assert "public_key_placeholder" not in lowered
    assert "password_placeholder" not in lowered


def test_select_choose_strategy_auto_historical_passed(tmp_path: Path, capsys) -> None:
    """Select from historical passed candidates artifact omitting explicit top-level passed flag."""
    candidates_path = tmp_path / "historical_candidates.json"
    candidates_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "sensitive": True,
                "candidates": [
                    {
                        "candidate": {
                            "source_name": "fixture",
                            "raw_name": "node",
                            "protocol": "vless",
                            "address": "example.invalid",
                            "port": 443,
                            "user_id": "00000000-0000-0000-0000-000000000000",
                            "security": "reality",
                            "server_name": "www.cloudflare.com",
                            "public_key": "PUBLIC_KEY_PLACEHOLDER",
                            "password": "PASSWORD_PLACEHOLDER",
                            "supported": True,
                            "raw_uri": "vless://00000000-0000-0000-0000-000000000000@example.invalid:443",
                        },
                        "probe": {
                            "candidate_id": "candidate-001",
                            "home_status": 200,
                            "query_status": 200,
                            "blocked": False,
                            "timeout": False,
                            "error": None,
                            "failure_markers": [],
                            "latency_ms": 10,
                            "checked_at": "2026-05-27T00:00:00Z",
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    exit_code = cli.main(
        [
            "select",
            "choose",
            "--candidates",
            str(candidates_path),
            "--strategy",
            "auto",
            "--output",
            str(tmp_path / "selected_candidate.json"),
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 0
    assert "selection_method: first" in captured.out or "selection_method: fallback:first" in captured.out
    assert "no_passed_candidate" not in captured.out
    assert "no_passed_candidate" not in captured.err
    _assert_no_secrets(captured.out + captured.err)
