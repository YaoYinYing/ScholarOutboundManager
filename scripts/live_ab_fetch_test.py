"""Run one local live A/B smoke test for subscription fetch and parse behavior."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from scholar_outbound_manager.state.atomic_write import atomic_write_json

_URL_PATTERN = re.compile(r"https?://\S+")
_VLESS_PATTERN = re.compile(r"vless://\S+", re.IGNORECASE)
_UUID_PATTERN = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
_PBK_PATTERN = re.compile(r"(?i)\b(?:pbk|public_key)\s*[:=]\s*([^\s&]+)")
_SECRET_PATTERN = re.compile(r"(?i)\b(?:token|secret|password)\s*[:=]\s*([^\s&]+)")


def read_link_file(path: str | Path) -> list[str]:
    """Read one local link file while ignoring empty lines and comments."""
    link_path = Path(path)
    links: list[str] = []
    for raw_line in link_path.read_text(encoding="utf-8").splitlines():
        stripped = raw_line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        links.append(stripped)
    return links


def build_group_config(group_name: str, links: list[str], work_dir: str | Path, xray_binary: str) -> dict[str, object]:
    """Build one local-only config payload for a fetch smoke-test group."""
    group_dir = Path(work_dir) / group_name
    subscriptions = [
        {
            "name": f"{group_name}_{index:03d}",
            "url": link,
            "format": "auto",
            "enabled": True,
            "headers": {},
        }
        for index, link in enumerate(links, start=1)
    ]
    return {
        "subscriptions": subscriptions,
        "filters": {
            "include_keywords": [],
            "exclude_keywords": [],
            "deprioritize_keywords": [],
        },
        "probe": {
            "timeout_seconds": 15,
            "concurrency": 1,
            "cache_ttl_hours": 24,
            "failure_backoff_hours": 48,
            "allow_network_probe": False,
        },
        "xray": {
            "binary_path": xray_binary,
            "runtime_dir": str(group_dir / ".runtime"),
            "local_socks_host": "127.0.0.1",
            "local_socks_port": 0,
        },
        "output": {
            "outbounds_path": str(group_dir / "generated" / "outbounds.json"),
            "routes_path": str(group_dir / "generated" / "routes.json"),
            "manifest_path": str(group_dir / "generated" / "manifest.json"),
            "history_dir": str(group_dir / "history"),
        },
        "generation": {
            "tag_prefix": "google-scholar-node-",
            "max_passed_nodes": 3,
            "fallback_blackhole_tag": "google-scholar-unavailable",
            "previous_output_max_age_hours": 168,
        },
        "routing": {
            "mode": "dedicated_inbound",
            "inbound_tags": ["google-scholar-in"],
            "fail_closed": True,
        },
    }


def write_group_config(path: str | Path, payload: dict[str, object]) -> None:
    """Write one YAML config for a smoke-test group."""
    config_path = Path(path)
    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")


def redact_live_output(text: str) -> str:
    """Redact URLs, proxy URIs, UUIDs, and obvious secret values from CLI output."""
    redacted = _URL_PATTERN.sub("<REDACTED_URL>", text)
    redacted = _VLESS_PATTERN.sub("<REDACTED_VLESS_URI>", redacted)
    redacted = _UUID_PATTERN.sub("<REDACTED_UUID>", redacted)
    redacted = _PBK_PATTERN.sub(lambda match: match.group(0).split(match.group(1))[0] + "<REDACTED>", redacted)
    redacted = _SECRET_PATTERN.sub(lambda match: match.group(0).split(match.group(1))[0] + "<REDACTED>", redacted)
    return redacted


def summarize_candidate_artifact(path: str | Path) -> dict[str, object]:
    """Summarize one sensitive candidate artifact without printing candidate contents."""
    artifact_path = Path(path)
    if not artifact_path.exists():
        return {
            "schema_version": None,
            "sensitive": None,
            "source_count": 0,
            "fetched_count": 0,
            "failed_count": 0,
            "parsed_count": 0,
            "unsupported_count": 0,
            "candidate_count": 0,
            "supported_count": 0,
        }

    payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    candidates = payload.get("candidates", [])
    supported_count = sum(
        1
        for candidate in candidates
        if isinstance(candidate, dict) and candidate.get("supported") is True
    )
    return {
        "schema_version": payload.get("schema_version"),
        "sensitive": payload.get("sensitive"),
        "source_count": payload.get("source_count", 0),
        "fetched_count": payload.get("fetched_count", 0),
        "failed_count": payload.get("failed_count", 0),
        "parsed_count": payload.get("parsed_count", 0),
        "unsupported_count": payload.get("unsupported_count", 0),
        "candidate_count": len(candidates) if isinstance(candidates, list) else 0,
        "supported_count": supported_count,
    }


def run_fetch_command(
    config_path: str | Path,
    output_path: str | Path,
    *,
    cwd: str | Path | None = None,
    runner: Any = subprocess.run,
) -> subprocess.CompletedProcess[str]:
    """Run the fetch CLI with explicit network opt-in."""
    command = [
        sys.executable,
        "-m",
        "scholar_outbound_manager.cli",
        "fetch",
        "--config",
        str(config_path),
        "--output",
        str(output_path),
        "--allow-network-fetch",
    ]
    return runner(
        command,
        cwd=str(cwd or REPO_ROOT),
        text=True,
        capture_output=True,
        check=False,
    )


def run_group(
    *,
    group_label: str,
    link_file: str | Path,
    work_dir: str | Path,
    xray_binary: str,
    runner: Any = subprocess.run,
) -> tuple[dict[str, object], str, str]:
    """Run one group fetch flow and return its redacted summary plus CLI output."""
    links = read_link_file(link_file)
    group_dir = Path(work_dir) / group_label
    config_path = group_dir / "config.yaml"
    output_path = group_dir / "candidates.json"
    write_group_config(
        config_path,
        build_group_config(group_label, links, work_dir, xray_binary),
    )

    result = run_fetch_command(config_path, output_path, cwd=REPO_ROOT, runner=runner)
    stdout_redacted = redact_live_output(result.stdout)
    stderr_redacted = redact_live_output(result.stderr)
    artifact_summary = summarize_candidate_artifact(output_path)
    group_summary = {
        "link_count": len(links),
        "exit_code": result.returncode,
        "source_count": artifact_summary["source_count"],
        "fetched_count": artifact_summary["fetched_count"],
        "failed_count": artifact_summary["failed_count"],
        "parsed_count": artifact_summary["parsed_count"],
        "supported_count": artifact_summary["supported_count"],
        "unsupported_count": artifact_summary["unsupported_count"],
        "output_path": str(output_path),
    }
    return group_summary, stdout_redacted, stderr_redacted


def build_live_ab_summary(valid_group: dict[str, object], invalid_group: dict[str, object]) -> dict[str, object]:
    """Build one redacted A/B summary payload."""
    return {
        "schema_version": 1,
        "groups": {
            "valid": valid_group,
            "invalid": invalid_group,
        },
        "interpretation": {
            "valid_fetch_ok": bool(
                valid_group.get("exit_code") == 0 and int(valid_group.get("parsed_count", 0)) > 0
            ),
            "invalid_failed_safely": bool(
                invalid_group.get("exit_code") != 0 or int(invalid_group.get("parsed_count", 0)) == 0
            ),
            "secrets_redacted": True,
        },
    }


def print_group_output(group_label: str, stdout_redacted: str, stderr_redacted: str) -> None:
    """Print one group's redacted CLI output."""
    if stdout_redacted.strip():
        print(f"[{group_label}] fetch stdout:")
        print(stdout_redacted.rstrip())
    if stderr_redacted.strip():
        if stdout_redacted.strip():
            print()
        print(f"[{group_label}] fetch stderr:")
        print(stderr_redacted.rstrip())


def build_parser() -> argparse.ArgumentParser:
    """Build the live A/B smoke-test argument parser."""
    parser = argparse.ArgumentParser(prog="live_ab_fetch_test.py")
    parser.add_argument("--valid-links", required=True)
    parser.add_argument("--invalid-links", required=True)
    parser.add_argument("--work-dir", required=True)
    parser.add_argument("--xray-binary", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run the local live A/B fetch smoke test."""
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        valid_group, valid_stdout, valid_stderr = run_group(
            group_label="valid",
            link_file=args.valid_links,
            work_dir=args.work_dir,
            xray_binary=args.xray_binary,
        )
        invalid_group, invalid_stdout, invalid_stderr = run_group(
            group_label="invalid",
            link_file=args.invalid_links,
            work_dir=args.work_dir,
            xray_binary=args.xray_binary,
        )
        summary = build_live_ab_summary(valid_group, invalid_group)
        summary_path = Path(args.work_dir) / "summary.json"
        atomic_write_json(summary_path, summary)
    except Exception as exc:  # pragma: no cover - CLI boundary
        print(f"Error: {redact_live_output(str(exc))}", file=sys.stderr)
        return 1

    print_group_output("valid", valid_stdout, valid_stderr)
    if valid_stdout.strip() or valid_stderr.strip():
        print()
    print_group_output("invalid", invalid_stdout, invalid_stderr)
    if invalid_stdout.strip() or invalid_stderr.strip():
        print()
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
