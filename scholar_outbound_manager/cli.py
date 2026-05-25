"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager import __version__
from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.generation import write_generation_outputs
from scholar_outbound_manager.io import load_candidates
from scholar_outbound_manager.runtime import prepare_candidate_runtime
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.xray.process import test_xray_config

UNIMPLEMENTED_MESSAGE = "Subcommand '{name}' is not implemented in Phase 0.5."


def build_parser() -> argparse.ArgumentParser:
    """Build the top-level argument parser."""
    parser = argparse.ArgumentParser(prog="scholar-outbound-manager")
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
    )

    subparsers = parser.add_subparsers(dest="command")

    for command_name in ("fetch", "probe"):
        subparser = subparsers.add_parser(command_name)
        subparser.add_argument("--config", default="config.yaml")
        subparser.set_defaults(handler=_handle_unimplemented)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--config", default="config.yaml")
    generate_parser.add_argument("--candidates", required=True)
    generate_parser.set_defaults(handler=_handle_generate)

    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--config", default="config.yaml")
    run_parser.add_argument("--candidates", required=True)
    run_parser.add_argument("--candidate-index", type=int, default=0)
    run_parser.add_argument("--runtime-config-name", default="candidate_runtime.json")
    run_parser.add_argument("--test-config", action="store_true")
    run_parser.add_argument("--xray-test-timeout", type=float, default=10.0)
    run_parser.set_defaults(handler=_handle_run)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--config", default="config.yaml")
    inspect_parser.add_argument("--manifest", default="generated/google_scholar_manifest.json")
    inspect_parser.set_defaults(handler=_handle_unimplemented)

    return parser


def _handle_unimplemented(args: argparse.Namespace) -> int:
    """Handle a declared but not yet implemented subcommand."""
    print(UNIMPLEMENTED_MESSAGE.format(name=args.command))
    return 2


def _handle_generate(args: argparse.Namespace) -> int:
    """Generate offline Scholar outbound artifacts from a local candidate file."""
    try:
        config = load_config(args.config)
        candidates = load_candidates(args.candidates)
        summary = write_generation_outputs(
            candidates=candidates,
            output_config=config.output,
            generation_config=config.generation,
            routing_config=config.routing,
        )
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Generated Scholar outbound artifacts.")
    print(f"selected_count: {summary['selected_count']}")
    print(f"rejected_count: {summary['rejected_count']}")
    print(f"outbounds_path: {summary['outbounds_path']}")
    print(f"routes_path: {summary['routes_path']}")
    print(f"manifest_path: {summary['manifest_path']}")
    return 0


def _handle_run(args: argparse.Namespace) -> int:
    """Prepare one candidate runtime config and optionally validate it with Xray."""
    try:
        _validate_runtime_config_name(args.runtime_config_name)
        _validate_xray_test_timeout(args.xray_test_timeout)
        config = load_config(args.config)
        candidates = load_candidates(args.candidates)
        selected_candidate = select_candidate_by_index(candidates, args.candidate_index)
        summary = prepare_candidate_runtime(
            candidate=selected_candidate,
            xray_config=config.xray,
            config_name=args.runtime_config_name,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Prepared Scholar runtime config.")
    print(f"candidate_index: {args.candidate_index}")
    print(f"candidate_name: {selected_candidate.raw_name}")
    print(f"runtime_config_path: {summary['runtime_config_path']}")
    print(f"local_socks_host: {summary['local_socks_host']}")
    print(f"local_socks_port: {summary['local_socks_port']}")

    if not args.test_config:
        return 0

    result = test_xray_config(
        binary_path=config.xray.binary_path,
        config_path=summary["runtime_config_path"],
        timeout_seconds=args.xray_test_timeout,
    )
    if result.returncode == 0 and not result.timed_out and result.error is None:
        print("Xray config test: passed")
        return 0

    print("Xray config test: failed")
    print(f"returncode: {result.returncode}")
    print(f"timed_out: {result.timed_out}")
    print(f"error: {result.error}")
    return 1


def _validate_runtime_config_name(config_name: str) -> None:
    """Validate that the runtime config name is a plain file name."""
    config_path = Path(config_name)
    if not config_name:
        raise ValueError("runtime-config-name must not be empty.")
    if config_path.is_absolute():
        raise ValueError("runtime-config-name must not be an absolute path.")
    if config_name in {".", ".."}:
        raise ValueError("runtime-config-name must be a file name.")
    if "/" in config_name or "\\" in config_name:
        raise ValueError("runtime-config-name must not contain path separators.")


def _validate_xray_test_timeout(timeout_seconds: float) -> None:
    """Validate the Xray config test timeout value."""
    if timeout_seconds <= 0:
        raise ValueError("xray-test-timeout must be greater than 0.")


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command-line interface."""
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        return int(exc.code)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.print_help()
        return 0
    return int(handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
