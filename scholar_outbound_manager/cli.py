"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from scholar_outbound_manager import __version__
from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.generation import write_generation_outputs
from scholar_outbound_manager.io import load_candidates

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

    for command_name in ("fetch", "probe", "run"):
        subparser = subparsers.add_parser(command_name)
        subparser.add_argument("--config", default="config.yaml")
        subparser.set_defaults(handler=_handle_unimplemented)

    generate_parser = subparsers.add_parser("generate")
    generate_parser.add_argument("--config", default="config.yaml")
    generate_parser.add_argument("--candidates", required=True)
    generate_parser.set_defaults(handler=_handle_generate)

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
