"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from collections.abc import Sequence
from pathlib import Path

from scholar_outbound_manager import __version__
from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.doctor import build_doctor_report
from scholar_outbound_manager.doctor import format_doctor_report
from scholar_outbound_manager.environment import format_runtime_environment_inspection
from scholar_outbound_manager.environment import inspect_runtime_environment
from scholar_outbound_manager.fetcher import build_url_opener
from scholar_outbound_manager.fetcher import fetch_enabled_subscriptions
from scholar_outbound_manager.fetcher import FetchErrorRecord
from scholar_outbound_manager.fetcher import FetchTransportOptions
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
from scholar_outbound_manager.sidecar import SidecarRuntimeOptions
from scholar_outbound_manager.sidecar import build_socks_outbound_snippet
from scholar_outbound_manager.sidecar import inspect_sidecar_runtime
from scholar_outbound_manager.sidecar import prepare_sidecar_runtime
from scholar_outbound_manager.sidecar import start_sidecar_runtime
from scholar_outbound_manager.sidecar import stop_sidecar_runtime
from scholar_outbound_manager.state.candidate_artifact import build_candidate_artifact
from scholar_outbound_manager.state.candidate_artifact import write_candidate_artifact
from scholar_outbound_manager.state.probe_state import write_probe_artifacts
from scholar_outbound_manager.systemd_sidecar import SystemdSidecarOptions
from scholar_outbound_manager.systemd_sidecar import build_systemd_sidecar_paths
from scholar_outbound_manager.systemd_sidecar import ensure_system_user
from scholar_outbound_manager.systemd_sidecar import install_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_sidecar_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_socks_outbound_snippet_for_sidecar
from scholar_outbound_manager.systemd_sidecar import run_systemctl
from scholar_outbound_manager.systemd_sidecar import stage_systemd_sidecar_files
from scholar_outbound_manager.xray.binary import detect_xray_platform
from scholar_outbound_manager.xray.binary import inspect_xray_binary
from scholar_outbound_manager.xray.binary import install_xray_binary
from scholar_outbound_manager.xray.process import is_managed_xray_process_alive
from scholar_outbound_manager.xray.process import read_managed_pid_file
from scholar_outbound_manager.xray.process import terminate_managed_xray_from_pid_file
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
    fetch_parser.add_argument("--proxy-url")
    fetch_parser.add_argument("--user-agent")
    fetch_parser.set_defaults(handler=_handle_fetch)

    doctor_parser = subparsers.add_parser("doctor")
    doctor_parser.add_argument("--config", default="config.yaml")
    doctor_parser.add_argument("--candidates")
    doctor_parser.add_argument("--require-network-probe-ready", action="store_true")
    doctor_parser.add_argument("--require-passed-candidates", action="store_true")
    doctor_parser.set_defaults(handler=_handle_doctor)

    environment_parser = subparsers.add_parser("environment")
    environment_parser.set_defaults(handler=_handle_environment)

    probe_parser = subparsers.add_parser("probe")
    probe_parser.add_argument("--config", default="config.yaml")
    probe_parser.add_argument("--candidates", required=True)
    probe_parser.add_argument("--summary-output", default="state_data/probe_summary.json")
    probe_parser.add_argument("--passed-candidates-output", default="state_data/passed_candidates.json")
    probe_parser.add_argument("--max-candidates", type=int)
    probe_parser.add_argument("--parallel", type=int)
    probe_parser.add_argument("--max-passed", type=int)
    probe_parser.add_argument("--keep-all-passed", action="store_true")
    probe_parser.add_argument("--include-unsupported", action="store_true")
    probe_parser.add_argument("--no-stop-after-max-passed", action="store_true")
    probe_parser.add_argument("--query", default="ppr")
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

    generate_parser = subparsers.add_parser(
        "generate",
        help="Export legacy offline Xray fragments without modifying production configuration.",
        description=(
            "Deprecated for production integration; prefer the sidecar service workflow."
        ),
    )
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

    xray_parser = subparsers.add_parser("xray")
    xray_subparsers = xray_parser.add_subparsers(dest="xray_command")

    xray_inspect_parser = xray_subparsers.add_parser("inspect")
    xray_inspect_parser.add_argument("--path", required=True)
    xray_inspect_parser.set_defaults(handler=_handle_xray_inspect)

    xray_install_parser = xray_subparsers.add_parser("install")
    xray_install_parser.add_argument("--install-dir", required=True)
    xray_install_parser.add_argument("--version", default="latest")
    xray_install_parser.add_argument("--allow-download", action="store_true")
    xray_install_parser.add_argument("--os")
    xray_install_parser.add_argument("--arch")
    xray_install_parser.set_defaults(handler=_handle_xray_install)

    xray_managed_status_parser = xray_subparsers.add_parser("managed-status")
    xray_managed_status_parser.add_argument("--pid-file", required=True)
    xray_managed_status_parser.add_argument("--binary-path", required=True)
    xray_managed_status_parser.add_argument("--config-path")
    xray_managed_status_parser.set_defaults(handler=_handle_xray_managed_status)

    xray_managed_clean_parser = xray_subparsers.add_parser("managed-clean")
    xray_managed_clean_parser.add_argument("--pid-file", required=True)
    xray_managed_clean_parser.add_argument("--binary-path", required=True)
    xray_managed_clean_parser.add_argument("--config-path")
    xray_managed_clean_parser.set_defaults(handler=_handle_xray_managed_clean)

    sidecar_parser = subparsers.add_parser("sidecar")
    sidecar_subparsers = sidecar_parser.add_subparsers(dest="sidecar_command")

    sidecar_prepare_parser = sidecar_subparsers.add_parser("prepare")
    _add_sidecar_runtime_arguments(sidecar_prepare_parser)
    sidecar_prepare_parser.set_defaults(handler=_handle_sidecar_prepare)

    sidecar_start_parser = sidecar_subparsers.add_parser("start")
    _add_sidecar_runtime_arguments(sidecar_start_parser)
    sidecar_start_parser.add_argument("--test-config-timeout", type=float, default=10.0)
    sidecar_start_parser.add_argument("--no-test-config", action="store_true")
    sidecar_start_parser.set_defaults(handler=_handle_sidecar_start)

    sidecar_status_parser = sidecar_subparsers.add_parser("status")
    sidecar_status_parser.add_argument("--config", default="config.yaml")
    sidecar_status_parser.add_argument("--runtime-config-name", default="scholar_sidecar_runtime.json")
    sidecar_status_parser.set_defaults(handler=_handle_sidecar_status)

    sidecar_stop_parser = sidecar_subparsers.add_parser("stop")
    sidecar_stop_parser.add_argument("--config", default="config.yaml")
    sidecar_stop_parser.add_argument("--runtime-config-name", default="scholar_sidecar_runtime.json")
    sidecar_stop_parser.set_defaults(handler=_handle_sidecar_stop)

    sidecar_snippet_parser = sidecar_subparsers.add_parser("snippet")
    sidecar_snippet_parser.add_argument("--listen-host", default="127.0.0.1")
    sidecar_snippet_parser.add_argument("--listen-port", type=int, default=19080)
    sidecar_snippet_parser.add_argument("--tag", default="scholar-sidecar-socks-out")
    sidecar_snippet_parser.set_defaults(handler=_handle_sidecar_snippet)

    sidecar_service_render_parser = sidecar_subparsers.add_parser("service-render")
    _add_sidecar_service_arguments(sidecar_service_render_parser)
    sidecar_service_render_parser.set_defaults(handler=_handle_sidecar_service_render)

    sidecar_service_stage_parser = sidecar_subparsers.add_parser("service-stage")
    _add_sidecar_service_arguments(sidecar_service_stage_parser)
    sidecar_service_stage_parser.add_argument("--config", default="config.yaml")
    sidecar_service_stage_parser.add_argument("--candidates", required=True)
    sidecar_service_stage_parser.add_argument("--candidate-index", type=int, default=0)
    sidecar_service_stage_parser.add_argument("--source-xray-binary")
    sidecar_service_stage_parser.set_defaults(handler=_handle_sidecar_service_stage)

    sidecar_service_install_parser = sidecar_subparsers.add_parser("service-install")
    _add_sidecar_service_arguments(sidecar_service_install_parser)
    sidecar_service_install_parser.set_defaults(handler=_handle_sidecar_service_install)

    for action in ("start", "stop", "restart", "status", "enable", "disable"):
        action_parser = sidecar_subparsers.add_parser(f"service-{action}")
        action_parser.add_argument("--unit-name", default="scholar-outbound-sidecar.service")
        action_parser.set_defaults(handler=_make_sidecar_service_action_handler(action))

    sidecar_service_snippet_parser = sidecar_subparsers.add_parser("service-snippet")
    sidecar_service_snippet_parser.add_argument("--listen-host", default="127.0.0.1")
    sidecar_service_snippet_parser.add_argument("--listen-port", type=int, default=19080)
    sidecar_service_snippet_parser.add_argument("--tag", default="scholar-sidecar-socks-out")
    sidecar_service_snippet_parser.set_defaults(handler=_handle_sidecar_service_snippet)

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
        transport_options = FetchTransportOptions(proxy_url=args.proxy_url)
        build_url_opener(transport_options)
        fetched, fetch_summary = _call_fetch_enabled_subscriptions(
            config.subscriptions,
            timeout_seconds=timeout_seconds,
            max_bytes=args.max_bytes,
            transport_options=transport_options,
            user_agent=args.user_agent,
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
            fetch_errors=fetch_summary.error_records,
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
    for category, count in _summarize_fetch_error_categories(fetch_summary.error_records).items():
        print(f"fetch_error_{category}_count: {count}")
    for status_code, count in _summarize_fetch_http_statuses(fetch_summary.error_records).items():
        print(f"http_status_{status_code}_count: {count}")
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

    print(
        "Warning: generate only exports offline Xray fragments. "
        "It does not modify production Xray/XrayR configuration. "
        "For production use, prefer the sidecar systemd workflow."
    )
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


def _call_fetch_enabled_subscriptions(
    sources,
    *,
    timeout_seconds: float,
    max_bytes: int,
    transport_options: FetchTransportOptions | None,
    user_agent: str | None,
):
    """Call the fetch layer while remaining compatible with older test doubles."""
    try:
        return fetch_enabled_subscriptions(
            sources,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            transport_options=transport_options,
            user_agent=user_agent,
        )
    except TypeError as exc:
        if "user_agent" not in str(exc):
            raise
        return fetch_enabled_subscriptions(
            sources,
            timeout_seconds=timeout_seconds,
            max_bytes=max_bytes,
            transport_options=transport_options,
        )


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
    """Probe local candidates and write review-safe probe artifacts."""
    try:
        _validate_positive_int_or_none(args.max_candidates, "max-candidates")
        _validate_positive_int_or_none(args.parallel, "parallel")
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
        parallel_workers = args.parallel
        if parallel_workers is None:
            parallel_workers = config.probe.concurrency if config.probe.concurrency > 0 else 1
        keep_all_passed = args.keep_all_passed
        batch_options = BatchProbeOptions(
            candidate_options=candidate_options,
            max_workers=parallel_workers,
            max_candidates=args.max_candidates,
            max_passed=None if keep_all_passed else args.max_passed,
            stop_after_max_passed=False if keep_all_passed else not args.no_stop_after_max_passed,
            keep_all_passed=keep_all_passed,
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
    print(f"parallel_workers: {summary.parallel_workers}")
    print(f"keep_all_passed: {str(summary.keep_all_passed).lower()}")
    print(f"retained_passed_count: {summary.retained_passed_count}")
    print(f"truncated: {str(summary.truncated).lower()}")
    print(f"summary_path: {artifacts['summary_path']}")
    print(f"passed_candidates_path: {artifacts['passed_candidates_path']}")
    return 0 if summary.passed_count > 0 else 2


def _handle_environment(args: argparse.Namespace) -> int:
    """Inspect local runtime hints without probing or starting Xray."""
    del args
    try:
        inspection = inspect_runtime_environment()
    except Exception as exc:  # pragma: no cover - defensive CLI boundary
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(format_runtime_environment_inspection(inspection))
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


def _handle_xray_inspect(args: argparse.Namespace) -> int:
    """Inspect one local Xray binary path without downloading anything."""
    info = inspect_xray_binary(args.path)
    print("Xray binary:")
    print(f"path: {info.path}")
    print(f"exists: {'true' if info.exists else 'false'}")
    print(f"executable: {'true' if info.executable else 'false'}")
    print(f"version: {info.version or ''}")
    print(f"error: {info.error or ''}")
    return 0 if info.exists and info.executable else 1


def _handle_xray_install(args: argparse.Namespace) -> int:
    """Explicitly install an Xray binary into a local ignored directory."""
    if not args.allow_download:
        print(
            "Error: --allow-download is required before downloading Xray.",
            file=sys.stderr,
        )
        return 1

    try:
        platform_asset = None
        if args.os is not None or args.arch is not None:
            platform_asset = detect_xray_platform(system=args.os, machine=args.arch)
        result = install_xray_binary(
            version=args.version,
            install_dir=args.install_dir,
            allow_download=True,
            platform_asset=platform_asset,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if result.installed and result.error is None:
        print("Installed Xray binary.")
        print(f"binary_path: {result.binary_path}")
        print(f"version: {result.version or ''}")
        return 0

    print(f"Error: {result.error or 'Xray installation failed.'}", file=sys.stderr)
    return 1


def _handle_xray_managed_status(args: argparse.Namespace) -> int:
    """Report managed Xray ownership status for one pid file."""
    pid_payload = read_managed_pid_file(args.pid_file)
    alive = is_managed_xray_process_alive(
        args.pid_file,
        expected_binary_path=args.binary_path,
        expected_config_path=args.config_path,
    )
    if pid_payload is None:
        ownership = "missing"
    elif alive:
        ownership = "matched"
    else:
        ownership = "unmatched"

    print("Managed Xray process:")
    print(f"pid_file: {args.pid_file}")
    print(f"alive: {'true' if alive else 'false'}")
    print(f"ownership: {ownership}")
    return 0


def _handle_xray_managed_clean(args: argparse.Namespace) -> int:
    """Terminate one project-managed Xray process only when ownership matches."""
    pid_payload = read_managed_pid_file(args.pid_file)
    if pid_payload is None:
        terminated = terminate_managed_xray_from_pid_file(
            args.pid_file,
            expected_binary_path=args.binary_path,
            expected_config_path=args.config_path,
        )
        print(f"managed_process_terminated: {'true' if terminated else 'false'}")
        return 0

    if not is_managed_xray_process_alive(
        args.pid_file,
        expected_binary_path=args.binary_path,
        expected_config_path=args.config_path,
    ):
        terminated = terminate_managed_xray_from_pid_file(
            args.pid_file,
            expected_binary_path=args.binary_path,
            expected_config_path=args.config_path,
        )
        print(f"managed_process_terminated: {'true' if terminated else 'false'}")
        pid_file_exists = Path(args.pid_file).exists()
        return 0 if not pid_file_exists else 1

    terminated = terminate_managed_xray_from_pid_file(
        args.pid_file,
        expected_binary_path=args.binary_path,
        expected_config_path=args.config_path,
    )
    print(f"managed_process_terminated: {'true' if terminated else 'false'}")
    return 0 if terminated else 1


def _handle_sidecar_prepare(args: argparse.Namespace) -> int:
    """Prepare one isolated sidecar runtime config without starting Xray."""
    try:
        config = load_config(args.config)
        candidates = load_candidates(args.candidates)
        candidate = select_candidate_by_index(candidates, args.candidate_index)
        options = _build_sidecar_options(args)
        summary = prepare_sidecar_runtime(
            candidate=candidate,
            xray_config=config.xray,
            options=options,
            candidate_id=f"candidate-{args.candidate_index:03d}",
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Prepared Scholar sidecar runtime.")
    print(f"runtime_config_path: {summary.runtime_config_path}")
    print(f"listen_host: {summary.listen_host}")
    print(f"listen_port: {summary.listen_port}")
    print(f"candidate_protocol: {summary.candidate_protocol}")
    print(f"pid_file_path: {summary.pid_file_path}")
    print(f"metadata_file_path: {summary.metadata_file_path}")
    return 0


def _handle_sidecar_start(args: argparse.Namespace) -> int:
    """Prepare and start one isolated sidecar runtime."""
    try:
        if not args.no_test_config:
            _validate_positive_float(args.test_config_timeout, "test-config-timeout")
        config = load_config(args.config)
        candidates = load_candidates(args.candidates)
        candidate = select_candidate_by_index(candidates, args.candidate_index)
        options = _build_sidecar_options(args)
        prepared = prepare_sidecar_runtime(
            candidate=candidate,
            xray_config=config.xray,
            options=options,
            candidate_id=f"candidate-{args.candidate_index:03d}",
        )
        summary = start_sidecar_runtime(
            config.xray,
            prepared,
            test_config_timeout_seconds=None if args.no_test_config else args.test_config_timeout,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Started Scholar sidecar runtime.")
    print(f"started: {'true' if summary.started else 'false'}")
    print(f"listen_host: {summary.listen_host}")
    print(f"listen_port: {summary.listen_port}")
    print(f"pid_file_path: {summary.pid_file_path}")
    print(f"runtime_config_path: {summary.runtime_config_path}")
    if summary.error:
        print(f"error: {summary.error}")
    return 0 if summary.started else 1


def _handle_sidecar_status(args: argparse.Namespace) -> int:
    """Inspect one sidecar runtime through its managed pid file."""
    try:
        config = load_config(args.config)
        options = _build_sidecar_status_options(args.runtime_config_name)
        runtime_dir = Path(config.xray.runtime_dir)
        runtime_config_path = runtime_dir / options.runtime_config_name
        pid_file_path = runtime_dir / options.pid_file_name
        inspection = inspect_sidecar_runtime(
            pid_file_path,
            expected_binary_path=config.xray.binary_path,
            expected_config_path=runtime_config_path,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Scholar sidecar runtime:")
    print(f"pid_file: {pid_file_path}")
    print(f"alive: {'true' if inspection['alive'] else 'false'}")
    print(f"ownership_matched: {'true' if inspection['ownership_matched'] else 'false'}")
    return 0


def _handle_sidecar_stop(args: argparse.Namespace) -> int:
    """Stop one managed sidecar runtime without touching external Xray services."""
    try:
        config = load_config(args.config)
        options = _build_sidecar_status_options(args.runtime_config_name)
        runtime_dir = Path(config.xray.runtime_dir)
        runtime_config_path = runtime_dir / options.runtime_config_name
        pid_file_path = runtime_dir / options.pid_file_name
        terminated = stop_sidecar_runtime(
            pid_file_path,
            expected_binary_path=config.xray.binary_path,
            expected_config_path=runtime_config_path,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Stopped Scholar sidecar runtime.")
    print(f"terminated: {'true' if terminated else 'false'}")
    return 0


def _handle_sidecar_snippet(args: argparse.Namespace) -> int:
    """Print one production-reference SOCKS outbound snippet."""
    try:
        snippet = build_socks_outbound_snippet(
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            tag=args.tag,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(snippet, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _handle_sidecar_service_render(args: argparse.Namespace) -> int:
    """Render one production systemd sidecar unit to stdout."""
    try:
        options = _build_systemd_sidecar_options(args)
        paths = build_systemd_sidecar_paths(options)
        unit_text = render_sidecar_systemd_unit(options, paths)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(unit_text, end="")
    return 0


def _handle_sidecar_service_stage(args: argparse.Namespace) -> int:
    """Stage production sidecar files without installing or starting systemd."""
    try:
        options = _build_systemd_sidecar_options(args)
        if _service_paths_require_root(options) and os.geteuid() != 0:
            raise PermissionError(
                "service-stage requires root for /opt, /etc, or /var targets; use root or custom paths."
            )
        config = load_config(args.config)
        candidates = load_candidates(args.candidates)
        candidate = select_candidate_by_index(candidates, args.candidate_index)
        paths = stage_systemd_sidecar_files(
            candidate=candidate,
            candidate_id=f"candidate-{args.candidate_index:03d}",
            xray_config=config.xray,
            options=options,
            source_xray_binary_path=args.source_xray_binary,
        )
    except (ConfigError, FileNotFoundError, PermissionError, ValueError, OSError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Staged Scholar production sidecar files.")
    print(f"xray_binary_path: {paths.xray_binary_path}")
    print(f"runtime_config_path: {paths.runtime_config_path}")
    print(f"metadata_path: {paths.metadata_path}")
    print(f"listen_host: {options.listen_host}")
    print(f"listen_port: {options.listen_port}")
    print(f"candidate_protocol: {candidate.protocol}")
    print("staged: true")
    return 0


def _handle_sidecar_service_install(args: argparse.Namespace) -> int:
    """Install one production systemd sidecar unit without starting it."""
    try:
        options = _build_systemd_sidecar_options(args)
        if _service_paths_require_root(options) and os.geteuid() != 0:
            raise PermissionError(
                "service-install requires root for /etc and system user setup; use root or custom paths."
            )
        paths = build_systemd_sidecar_paths(options)
        user_results = ensure_system_user(options)
        unit_text = render_sidecar_systemd_unit(options, paths)
        install_results = install_systemd_unit(unit_text, paths.unit_path)
    except (PermissionError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Installed Scholar production sidecar unit.")
    print("user_ensured: true")
    print(f"unit_path: {paths.unit_path}")
    print("installed: true")
    if any(not result.ok for result in [*user_results, *install_results]):
        return 1
    return 0


def _make_sidecar_service_action_handler(action: str):
    """Build one CLI handler for a simple systemctl-backed sidecar action."""

    def _handler(args: argparse.Namespace) -> int:
        try:
            result = run_systemctl(action, args.unit_name)
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        print(f"action: {action}")
        print(f"unit_name: {args.unit_name}")
        print(f"returncode: {result.returncode}")
        return 0 if result.ok else 1

    return _handler


def _handle_sidecar_service_snippet(args: argparse.Namespace) -> int:
    """Print one production systemd-sidecar SOCKS outbound snippet."""
    try:
        snippet = render_socks_outbound_snippet_for_sidecar(
            listen_host=args.listen_host,
            listen_port=args.listen_port,
            tag=args.tag,
        )
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(snippet, indent=2, ensure_ascii=False, sort_keys=True))
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


def _add_sidecar_runtime_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared sidecar prepare/start arguments."""
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--candidates", required=True)
    parser.add_argument("--candidate-index", type=int, default=0)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=19080)
    parser.add_argument("--runtime-config-name", default="scholar_sidecar_runtime.json")


def _add_sidecar_service_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared production systemd sidecar arguments."""
    parser.add_argument("--unit-name", default="scholar-outbound-sidecar.service")
    parser.add_argument("--service-user", default="scholar-sidecar")
    parser.add_argument("--service-group", default="scholar-sidecar")
    parser.add_argument("--install-root", default="/opt/scholar-outbound-manager")
    parser.add_argument("--config-dir", default="/etc/scholar-outbound-manager")
    parser.add_argument("--state-dir", default="/var/lib/scholar-outbound-manager")
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=19080)
    parser.add_argument("--restart-policy", default="on-failure")
    parser.add_argument("--restart-sec", type=int, default=5)


def _build_sidecar_options(args: argparse.Namespace) -> SidecarRuntimeOptions:
    """Construct sidecar runtime options from CLI arguments."""
    return SidecarRuntimeOptions(
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        runtime_config_name=args.runtime_config_name,
    )


def _build_sidecar_status_options(runtime_config_name: str) -> SidecarRuntimeOptions:
    """Construct sidecar options for status/stop from the runtime config name."""
    _validate_runtime_config_name(runtime_config_name)
    return SidecarRuntimeOptions(runtime_config_name=runtime_config_name)


def _build_systemd_sidecar_options(args: argparse.Namespace) -> SystemdSidecarOptions:
    """Construct production systemd sidecar options from CLI arguments."""
    return SystemdSidecarOptions(
        unit_name=args.unit_name,
        service_user=args.service_user,
        service_group=args.service_group,
        install_root=args.install_root,
        config_dir=args.config_dir,
        state_dir=args.state_dir,
        listen_host=args.listen_host,
        listen_port=args.listen_port,
        restart_policy=args.restart_policy,
        restart_sec=args.restart_sec,
    )


def _service_paths_require_root(options: SystemdSidecarOptions) -> bool:
    """Return whether the configured production paths typically require root access."""
    protected_prefixes = ("/opt/", "/etc/", "/var/")
    configured_paths = (options.install_root, options.config_dir, options.state_dir)
    return any(path == prefix[:-1] or path.startswith(prefix) for path in configured_paths for prefix in protected_prefixes)


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


def _summarize_fetch_error_categories(error_records: list[FetchErrorRecord]) -> dict[str, int]:
    """Count fetch error categories for CLI summary output."""
    return dict(sorted(Counter(record.category for record in error_records).items()))


def _summarize_fetch_http_statuses(error_records: list[FetchErrorRecord]) -> dict[int, int]:
    """Count fetch HTTP status codes for CLI summary output."""
    return dict(
        sorted(
            Counter(record.http_status for record in error_records if record.http_status is not None).items()
        )
    )


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
