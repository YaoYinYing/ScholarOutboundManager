"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
from collections.abc import Sequence

from scholar_outbound_manager import __version__

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

    for command_name in ("fetch", "probe", "generate", "run"):
        subparser = subparsers.add_parser(command_name)
        subparser.add_argument("--config", default="config.yaml")
        subparser.set_defaults(handler=_handle_unimplemented)

    inspect_parser = subparsers.add_parser("inspect")
    inspect_parser.add_argument("--config", default="config.yaml")
    inspect_parser.add_argument("--manifest", default="generated/google_scholar_manifest.json")
    inspect_parser.set_defaults(handler=_handle_unimplemented)

    return parser


def _handle_unimplemented(args: argparse.Namespace) -> int:
    """Handle a declared but not yet implemented subcommand."""
    print(UNIMPLEMENTED_MESSAGE.format(name=args.command))
    return 2


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
