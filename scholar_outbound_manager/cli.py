"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager import __version__
from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.doctor import build_doctor_report
from scholar_outbound_manager.doctor import format_doctor_report
from scholar_outbound_manager.fetcher import fetch_enabled_subscriptions
from scholar_outbound_manager.generation import write_generation_outputs
from scholar_outbound_manager.inspect import format_generated_manifest_inspection
from scholar_outbound_manager.inspect import format_probe_summary_inspection
from scholar_outbound_manager.inspect import format_sensitive_candidates_inspection
from scholar_outbound_manager.inspect import inspect_generated_manifest
from scholar_outbound_manager.inspect import inspect_probe_summary
from scholar_outbound_manager.inspect import inspect_sensitive_candidates
from scholar_outbound_manager.io import load_candidate_bundle
from scholar_outbound_manager.io import load_candidates
from scholar_outbound_manager.parsers.filtering import filter_candidates
from scholar_outbound_manager.parsers.subscription import parse_fetched_subscriptions
from scholar_outbound_manager.probe.batch_probe import BatchProbeOptions
from scholar_outbound_manager.probe.batch_probe import probe_candidates_sequential
from scholar_outbound_manager.probe.candidate_probe import CandidateProbeOptions
from scholar_outbound_manager.runtime import prepare_candidate_runtime
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.state.candidate_artifact import build_candidate_artifact
from scholar_outbound_manager.state.candidate_artifact import write_candidate_artifact
from scholar_outbound_manager.state.probe_state import write_probe_artifacts
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

    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--config", default="config.yaml")
    fetch_parser.add_argument("--output", default="candidates.json")
    fetch_parser.add_argument("--allow-network-fetch", action="store_true")
    fetch_parser.add_argument("--timeout", type=float)
    fetch_parser.add_argument("--max-bytes", type=int, default=1_048_576)
    fetch_parser.set_defaults(handler=_handle_fetch)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config", default="config.yaml")
    doctor_parser.add_argument("--candidates")
    doctor_parser.add_argument("--require-network-probe-ready", action="store_true")
    doctor_parser.add_argument("--require-passed-candidates", action="store_true")
    doctor_parser.set_defaults(handler=_handle_doctor)

    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--config", default="config.yaml")
    probe_parser.add_argument("--candidates", required=True)
    probe_parser.add_argument("--summary-output", default="state_data/probe_summary.json")
    probe_parser.add_argument("--passed-candidates-output", default="state_data/passed_candidates.json")
    probe_parser.add_argument("--max-candidates", type=int)
    probe_parser.add_argument("--max-passed", type=int)
    probe_parser.add_argument("--include-unsupported", action="store_true")
    probe_parser.add_argument("--no-stop-after-max-passed", action="store_true")
    probe_parser.add_argument("--query", default="test")
    probe_parser.add_argument("--skip-query", action="store_true")
    probe_parser.add_argument("--startup-timeout", type=float, default=5.0)
    probe_parser.add_argument("--request-timeout", type=float)
    probe_parser.add_argument("--xray-test-timeout", type=float)
    probe_parser.add_argument("--runtime-config-name", default="candidate_probe_runtime.json")
    probe_parser.add_argument("--allow-network-probe", action="store_true")
    probe_parser.set_defaults(handler=_handle_probe)

    for command_name in ():
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
    inspect_parser.add_argument("--probe-summary")
    inspect_parser.add_argument("--manifest")
    inspect_parser.add_argument("--passed-candidates")
    inspect_parser.set_defaults(handler=_handle_inspect)

    return parser


def _handle_unimplemented(args: argparse.Namespace) -> int:
    """Handle a declared but not yet implemented subcommand."""
    print(UNIMPLEMENTED_MESSAGE.format(name=args.command))
    return 2


def _handle_fetch(args: argparse.Namespace) -> int:
    """Fetch enabled subscriptions into one local sensitive candidate artifact."""
    if not args.allow_network_fetch:
        print(
            "Error: --allow-network-fetch is required before downloading subscriptions.",
            file=sys.stderr,
        )
        return 1

    try:
        if args.timeout is not None:
            _validate_positive_float(args.timeout, "timeout")
        _validate_positive_int_or_none(args.max_bytes, "max-bytes")

        config = load_config(args.config)
        timeout_seconds = config.probe.timeout_seconds if args.timeout is None else args.timeout
        fetched, fetch_summary = fetch_enabled_subscriptions(
            config.subscriptions,
            timeout_seconds=timeout_seconds,
            max_bytes=args.max_bytes,
        )
        parsed_subscriptions = parse_fetched_subscriptions(
            fetched,
            format_by_source={source.name: source.format for source in config.subscriptions},
        )

        candidates = [
            candidate
            for parsed_subscription in parsed_subscriptions
            for candidate in parsed_subscription.candidates
        ]
        parsed_count = len(candidates)
        unsupported_count = sum(1 for candidate in candidates if not candidate.supported)
        payload = build_candidate_artifact(
            candidates,
            source_count=fetch_summary.source_count,
            fetched_count=fetch_summary.fetched_count,
            disabled_count=fetch_summary.disabled_count,
            failed_count=fetch_summary.failed_count,
            total_bytes=fetch_summary.total_bytes,
            parsed_count=parsed_count,
            unsupported_count=unsupported_count,
        )
        write_candidate_artifact(args.output, payload)
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    enabled_count = fetch_summary.source_count - fetch_summary.disabled_count
    supported_count = parsed_count - unsupported_count
    print("Fetched Scholar candidate subscriptions.")
    print(f"source_count: {fetch_summary.source_count}")
    print(f"enabled_count: {enabled_count}")
    print(f"disabled_count: {fetch_summary.disabled_count}")
    print(f"fetched_count: {fetch_summary.fetched_count}")
    print(f"failed_count: {fetch_summary.failed_count}")
    print(f"parsed_count: {parsed_count}")
    print(f"supported_count: {supported_count}")
    print(f"unsupported_count: {unsupported_count}")
    print(f"output_path: {args.output}")
    return 0 if fetch_summary.fetched_count > 0 and parsed_count > 0 else 2


def _handle_generate(args: argparse.Namespace) -> int:
    """Generate offline Scholar outbound artifacts from a local candidate file."""
    try:
        config = load_config(args.config)
        bundle = load_candidate_bundle(args.candidates)
        candidates, filtered_count = _filter_candidates_for_cli(bundle.candidates, config.filters)
        summary = write_generation_outputs(
            candidates=candidates,
            output_config=config.output,
            generation_config=config.generation,
            routing_config=config.routing,
            probe_results=_align_probe_results(bundle.candidates, bundle.probe_results, candidates),
        )
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Generated Scholar outbound artifacts.")
    print(f"loaded_count: {len(bundle.candidates)}")
    print(f"filtered_count: {len(candidates)}")
    print(f"filter_skipped_count: {filtered_count}")
    print(f"selected_count: {summary['selected_count']}")
    print(f"rejected_count: {summary['rejected_count']}")
    print(f"outbounds_path: {summary['outbounds_path']}")
    print(f"routes_path: {summary['routes_path']}")
    print(f"manifest_path: {summary['manifest_path']}")
    return 0


def _handle_doctor(args: argparse.Namespace) -> int:
    """Run local-only preflight checks without starting Xray or probing."""
    try:
        report = build_doctor_report(
            config_path=args.config,
            candidates_path=args.candidates,
            require_network_probe_ready=args.require_network_probe_ready,
            require_passed_candidates=args.require_passed_candidates,
        )
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(format_doctor_report(report))
    return report.exit_code


def _handle_probe(args: argparse.Namespace) -> int:
    """Probe local candidates sequentially and write review-safe probe artifacts."""
    try:
        _validate_positive_int_or_none(args.max_candidates, "max-candidates")
        _validate_positive_int_or_none(args.max_passed, "max-passed")
        _validate_positive_float(args.startup_timeout, "startup-timeout")
        if args.request_timeout is not None:
            _validate_positive_float(args.request_timeout, "request-timeout")
        if args.xray_test_timeout is not None:
            _validate_positive_float(args.xray_test_timeout, "xray-test-timeout")
        _validate_runtime_config_name(args.runtime_config_name)
        _validate_distinct_output_paths(args.summary_output, args.passed_candidates_output)

        config = load_config(args.config)
        _require_network_probe_opt_in(config.probe.allow_network_probe, args.allow_network_probe)
        loaded_candidates = load_candidates(args.candidates)
        candidates, filtered_out_count = _filter_candidates_for_cli(loaded_candidates, config.filters)
        candidate_options = CandidateProbeOptions(
            query=args.query,
            startup_timeout_seconds=args.startup_timeout,
            request_timeout_seconds=(
                config.probe.timeout_seconds if args.request_timeout is None else args.request_timeout
            ),
            xray_test_timeout_seconds=args.xray_test_timeout,
            runtime_config_name=args.runtime_config_name,
            probe_query=not args.skip_query,
        )
        batch_options = BatchProbeOptions(
            candidate_options=candidate_options,
            max_candidates=args.max_candidates,
            max_passed=(
                config.generation.max_passed_nodes if args.max_passed is None else args.max_passed
            ),
            stop_after_max_passed=not args.no_stop_after_max_passed,
            include_unsupported=args.include_unsupported,
        )
        summary = probe_candidates_sequential(candidates, config.xray, batch_options)
        artifacts = write_probe_artifacts(
            summary_path=args.summary_output,
            passed_candidates_path=args.passed_candidates_output,
            candidates=candidates,
            summary=summary,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Probed Scholar candidates.")
    print(f"loaded_count: {len(loaded_candidates)}")
    print(f"filtered_count: {len(candidates)}")
    print(f"filter_skipped_count: {filtered_out_count}")
    print(f"total_count: {summary.total_count}")
    print(f"attempted_count: {summary.attempted_count}")
    print(f"skipped_count: {summary.skipped_count}")
    print(f"passed_count: {summary.passed_count}")
    print(f"failed_count: {summary.failed_count}")
    print(f"summary_path: {artifacts['summary_path']}")
    print(f"passed_candidates_path: {artifacts['passed_candidates_path']}")
    return 0 if summary.passed_count > 0 else 2


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


def _handle_inspect(args: argparse.Namespace) -> int:
    """Inspect review-safe artifacts without printing sensitive credentials."""
    try:
        sections: list[str] = []
        probe_summary_path = args.probe_summary
        manifest_path = args.manifest
        passed_candidates_path = args.passed_candidates
        if probe_summary_path is None and manifest_path is None and passed_candidates_path is None:
            manifest_path = "generated/google_scholar_manifest.json"

        if probe_summary_path is not None:
            sections.append(format_probe_summary_inspection(inspect_probe_summary(probe_summary_path)))
        if manifest_path is not None:
            sections.append(format_generated_manifest_inspection(inspect_generated_manifest(manifest_path)))
        if passed_candidates_path is not None:
            sections.append(
                format_sensitive_candidates_inspection(
                    inspect_sensitive_candidates(passed_candidates_path)
                )
            )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("\n\n".join(sections))
    return 0


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


def _validate_positive_int_or_none(value: int | None, name: str) -> None:
    """Validate that an optional integer is positive when provided."""
    if value is not None and value <= 0:
        raise ValueError(f"{name} must be greater than 0.")


def _validate_positive_float(value: float, name: str) -> None:
    """Validate that a float argument is positive."""
    if value <= 0:
        raise ValueError(f"{name} must be greater than 0.")


def _validate_distinct_output_paths(summary_output: str, passed_candidates_output: str) -> None:
    """Validate that probe output paths do not point to the same location."""
    if Path(summary_output) == Path(passed_candidates_output):
        raise ValueError("summary-output and passed-candidates-output must be different paths.")


def _filter_candidates_for_cli(
    candidates: list,
    filter_config,
) -> tuple[list, int]:
    """Apply configured candidate filters and report how many entries were skipped."""
    filtered_candidates = filter_candidates(candidates, filter_config)
    return filtered_candidates, len(candidates) - len(filtered_candidates)


def _align_probe_results(
    loaded_candidates: list,
    loaded_probe_results: list,
    filtered_candidates: list,
) -> list | None:
    """Align loaded probe results with the filtered candidate list order."""
    if not loaded_probe_results or all(result is None for result in loaded_probe_results):
        return None

    indexed_probe_results = {
        id(candidate): probe_result
        for candidate, probe_result in zip(loaded_candidates, loaded_probe_results)
    }
    return [indexed_probe_results.get(id(candidate)) for candidate in filtered_candidates]


def _require_network_probe_opt_in(config_allows_network_probe: bool, cli_allows_network_probe: bool) -> None:
    """Require both config and CLI opt-in before starting network probing."""
    if not config_allows_network_probe:
        raise ValueError(
            "probe.allow_network_probe must be true before network probing may start."
        )
    if not cli_allows_network_probe:
        raise ValueError(
            "--allow-network-probe is required before starting Xray or sending Scholar HTTP requests."
        )


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
