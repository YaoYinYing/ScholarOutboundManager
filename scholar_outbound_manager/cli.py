"""Command-line interface entry point for ScholarOutboundManager."""

from __future__ import annotations

import argparse
import json
import os
from datetime import datetime
from datetime import timezone
import re
import socket
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
from scholar_outbound_manager.geo import build_geo_refresh_plan
from scholar_outbound_manager.geo import inspect_geo_database
from scholar_outbound_manager.geo import load_candidate_geo_cache
from scholar_outbound_manager.geo import summarize_candidate_geo_cache
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
from scholar_outbound_manager.probe.http_probe import SocksEndpoint
from scholar_outbound_manager.probe.http_probe import probe_http_via_socks
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_home_target
from scholar_outbound_manager.probe.scholar_classifier import build_scholar_query_target
from scholar_outbound_manager.probe.scholar_classifier import classify_scholar_access
from scholar_outbound_manager.runtime import prepare_candidate_runtime
from scholar_outbound_manager.selection_policy import explain_selection_policy
from scholar_outbound_manager.selection_policy import SelectionPolicyOptions
from scholar_outbound_manager.selection_policy import select_candidate_with_policy
from scholar_outbound_manager.selection import build_candidate_catalog
from scholar_outbound_manager.selection import build_selected_candidate_artifact
from scholar_outbound_manager.selection import catalog_to_dicts
from scholar_outbound_manager.selection import format_candidate_catalog_table
from scholar_outbound_manager.selection import load_candidate_payload
from scholar_outbound_manager.selection import load_selected_candidate_artifact
from scholar_outbound_manager.selection import select_candidate_by_id
from scholar_outbound_manager.selection import select_candidate_by_index
from scholar_outbound_manager.selection import write_selected_candidate_artifact
from scholar_outbound_manager.sidecar import SidecarRuntimeOptions
from scholar_outbound_manager.sidecar import build_socks_outbound_snippet
from scholar_outbound_manager.sidecar import inspect_sidecar_runtime
from scholar_outbound_manager.sidecar import prepare_sidecar_runtime
from scholar_outbound_manager.sidecar import start_sidecar_runtime
from scholar_outbound_manager.sidecar import stop_sidecar_runtime
from scholar_outbound_manager.sidecar_pool import build_pool_socks_outbound_snippets
from scholar_outbound_manager.sidecar_pool import build_sidecar_pool_plan
from scholar_outbound_manager.sidecar_pool import check_pool_ports_available
from scholar_outbound_manager.sidecar_pool import load_pool_plan
from scholar_outbound_manager.sidecar_pool import validate_pool_sidecar
from scholar_outbound_manager.sidecar_pool import write_pool_plan
from scholar_outbound_manager.state.candidate_artifact import build_candidate_artifact
from scholar_outbound_manager.state.candidate_artifact import write_candidate_artifact
from scholar_outbound_manager.state.artifact_lineage import build_probe_explanation
from scholar_outbound_manager.state.artifact_lineage import check_artifact_consistency
from scholar_outbound_manager.state.artifact_lineage import compute_artifact_hash
from scholar_outbound_manager.state.artifact_lineage import generate_run_id
from scholar_outbound_manager.state.artifact_lineage import load_artifact_payload
from scholar_outbound_manager.state.artifact_lineage import summarize_lineage_warning
from scholar_outbound_manager.state.probe_state import write_probe_artifacts
from scholar_outbound_manager.systemd_sidecar import SystemdSidecarOptions
from scholar_outbound_manager.systemd_sidecar import build_systemd_sidecar_paths
from scholar_outbound_manager.systemd_sidecar import ensure_system_user
from scholar_outbound_manager.systemd_sidecar import install_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_sidecar_systemd_unit
from scholar_outbound_manager.systemd_sidecar import render_socks_outbound_snippet_for_sidecar
from scholar_outbound_manager.systemd_sidecar import run_systemctl
from scholar_outbound_manager.systemd_sidecar import stage_single_xray_pool_files
from scholar_outbound_manager.systemd_sidecar import stage_systemd_sidecar_files
from scholar_outbound_manager.systemd_sidecar import summarize_command_results
from scholar_outbound_manager.systemd_sidecar import summarize_system_user_results
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

    geo_parser = subparsers.add_parser("geo")
    geo_subparsers = geo_parser.add_subparsers(dest="geo_command")

    geo_db_info_parser = geo_subparsers.add_parser("db-info")
    geo_db_info_parser.add_argument("--geo-db", required=True)
    geo_db_info_parser.set_defaults(handler=_handle_geo_db_info)

    geo_cache_inspect_parser = geo_subparsers.add_parser("cache-inspect")
    geo_cache_inspect_parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    geo_cache_inspect_parser.set_defaults(handler=_handle_geo_cache_inspect)

    geo_refresh_plan_parser = geo_subparsers.add_parser("refresh-plan")
    geo_refresh_plan_parser.add_argument("--candidates", required=True)
    geo_refresh_plan_parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    geo_refresh_plan_parser.add_argument("--refresh-expired", dest="refresh_expired", action="store_true", default=True)
    geo_refresh_plan_parser.add_argument("--no-refresh-expired", dest="refresh_expired", action="store_false")
    geo_refresh_plan_parser.set_defaults(handler=_handle_geo_refresh_plan)

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
    probe_parser.add_argument("--transport-retry-count", type=int, default=0)
    probe_parser.add_argument("--transport-retry-backoff", type=float, default=1.0)
    probe_parser.add_argument("--hysteria2-warmup-attempts", type=int, default=0)
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

    artifact_parser = subparsers.add_parser("artifact")
    artifact_subparsers = artifact_parser.add_subparsers(dest="artifact_command")

    artifact_check_parser = artifact_subparsers.add_parser("check")
    artifact_check_parser.add_argument("--candidates")
    artifact_check_parser.add_argument("--probe-summary")
    artifact_check_parser.add_argument("--passed-candidates")
    artifact_check_parser.set_defaults(handler=_handle_artifact_check)

    artifact_explain_probe_parser = artifact_subparsers.add_parser("explain-probe")
    artifact_explain_probe_parser.add_argument("--probe-summary", required=True)
    artifact_explain_probe_parser.add_argument("--label-regex")
    artifact_explain_probe_parser.add_argument("--candidate-id")
    artifact_explain_probe_parser.add_argument("--protocol")
    artifact_explain_probe_parser.add_argument("--error-category")
    artifact_explain_probe_parser.add_argument("--marker")
    artifact_explain_probe_parser.set_defaults(handler=_handle_artifact_explain_probe)

    select_parser = subparsers.add_parser("select")
    select_subparsers = select_parser.add_subparsers(dest="select_command")

    select_list_parser = select_subparsers.add_parser("list")
    select_list_parser.add_argument("--candidates", required=True)
    select_list_parser.add_argument("--json", action="store_true")
    select_list_parser.add_argument("--no-label", action="store_true")
    select_list_parser.set_defaults(handler=_handle_select_list)

    select_choose_parser = select_subparsers.add_parser("choose")
    select_choose_parser.add_argument("--candidates", required=True)
    select_choose_parser.add_argument("--candidate-id")
    select_choose_parser.add_argument("--candidate-index", type=int)
    select_choose_parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    select_choose_parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    select_choose_parser.add_argument("--host-geo", default="state_data/geo/host_geo.json")
    select_choose_parser.add_argument("--preferred-region-hint")
    select_choose_parser.add_argument("--prefer-geo", dest="prefer_geo", action="store_true", default=True)
    select_choose_parser.add_argument("--no-prefer-geo", dest="prefer_geo", action="store_false")
    select_choose_parser.add_argument("--output", default="state_data/selected_candidate.json")
    select_choose_parser.set_defaults(handler=_handle_select_choose)

    select_explain_parser = select_subparsers.add_parser("explain")
    select_explain_parser.add_argument("--candidates", required=True)
    select_explain_parser.add_argument("--candidate-id")
    select_explain_parser.add_argument("--candidate-index", type=int)
    select_explain_parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    select_explain_parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    select_explain_parser.add_argument("--host-geo", default="state_data/geo/host_geo.json")
    select_explain_parser.add_argument("--preferred-region-hint")
    select_explain_parser.add_argument("--prefer-geo", dest="prefer_geo", action="store_true", default=True)
    select_explain_parser.add_argument("--no-prefer-geo", dest="prefer_geo", action="store_false")
    select_explain_parser.set_defaults(handler=_handle_select_explain)

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
    sidecar_service_stage_parser.add_argument("--candidates")
    _add_candidate_selection_arguments(sidecar_service_stage_parser)
    sidecar_service_stage_parser.add_argument("--source-xray-binary")
    sidecar_service_stage_parser.add_argument("--skip-xray-binary-copy", action="store_true")
    sidecar_service_stage_parser.set_defaults(handler=_handle_sidecar_service_stage)

    sidecar_service_install_parser = sidecar_subparsers.add_parser("service-install")
    _add_sidecar_service_arguments(sidecar_service_install_parser)
    sidecar_service_install_parser.set_defaults(handler=_handle_sidecar_service_install)

    for action in ("start", "stop", "restart", "status", "enable", "disable"):
        action_parser = sidecar_subparsers.add_parser(f"service-{action}")
        action_parser.add_argument("--unit-name", default="scholar-outbound-sidecar.service")
        action_parser.set_defaults(handler=_make_sidecar_service_action_handler(action))

    sidecar_service_validate_parser = sidecar_subparsers.add_parser("service-validate")
    sidecar_service_validate_parser.add_argument("--unit-name", default="scholar-outbound-sidecar.service")
    sidecar_service_validate_parser.add_argument("--listen-host", default="127.0.0.1")
    sidecar_service_validate_parser.add_argument("--listen-port", type=int, default=19080)
    sidecar_service_validate_parser.add_argument("--query", default="ppr")
    sidecar_service_validate_parser.add_argument("--request-timeout", type=float, default=15.0)
    sidecar_service_validate_parser.set_defaults(handler=_handle_sidecar_service_validate)

    sidecar_service_snippet_parser = sidecar_subparsers.add_parser("service-snippet")
    sidecar_service_snippet_parser.add_argument("--listen-host", default="127.0.0.1")
    sidecar_service_snippet_parser.add_argument("--listen-port", type=int, default=19080)
    sidecar_service_snippet_parser.add_argument("--tag", default="scholar-sidecar-socks-out")
    sidecar_service_snippet_parser.set_defaults(handler=_handle_sidecar_service_snippet)

    sidecar_pool_parser = sidecar_subparsers.add_parser("pool")
    sidecar_pool_subparsers = sidecar_pool_parser.add_subparsers(dest="sidecar_pool_command")

    sidecar_pool_plan_parser = sidecar_pool_subparsers.add_parser("plan")
    sidecar_pool_plan_parser.add_argument("--candidates", required=True)
    sidecar_pool_plan_parser.add_argument("--output", default="state_data/sidecar_pool_plan.json")
    sidecar_pool_plan_parser.add_argument("--max-count", type=int)
    sidecar_pool_plan_parser.add_argument("--candidate-id", action="append", dest="candidate_ids")
    sidecar_pool_plan_parser.add_argument("--listen-host", default="127.0.0.1")
    sidecar_pool_plan_parser.add_argument("--base-port", type=int, default=19080)
    sidecar_pool_plan_parser.set_defaults(handler=_handle_sidecar_pool_plan)

    sidecar_pool_check_ports_parser = sidecar_pool_subparsers.add_parser("check-ports")
    sidecar_pool_check_ports_parser.add_argument("--plan", required=True)
    sidecar_pool_check_ports_parser.set_defaults(handler=_handle_sidecar_pool_check_ports)

    sidecar_pool_stage_parser = sidecar_pool_subparsers.add_parser("stage")
    sidecar_pool_stage_parser.add_argument("--config", required=True)
    sidecar_pool_stage_parser.add_argument("--candidates", required=True)
    sidecar_pool_stage_parser.add_argument("--plan", required=True)
    sidecar_pool_stage_parser.add_argument("--source-xray-binary")
    sidecar_pool_stage_parser.add_argument("--skip-xray-binary-copy", action="store_true")
    sidecar_pool_stage_parser.add_argument("--allow-port-conflict", action="store_true")
    _add_sidecar_service_arguments(sidecar_pool_stage_parser)
    sidecar_pool_stage_parser.set_defaults(handler=_handle_sidecar_pool_stage)

    sidecar_pool_validate_parser = sidecar_pool_subparsers.add_parser("validate")
    sidecar_pool_validate_parser.add_argument("--plan", required=True)
    sidecar_pool_validate_parser.add_argument("--query", default="ppr")
    sidecar_pool_validate_parser.add_argument("--request-timeout", type=float, default=15.0)
    sidecar_pool_validate_parser.set_defaults(handler=_handle_sidecar_pool_validate)

    sidecar_pool_snippets_parser = sidecar_pool_subparsers.add_parser("snippets")
    sidecar_pool_snippets_parser.add_argument("--plan", required=True)
    sidecar_pool_snippets_parser.add_argument("--json", action="store_true")
    sidecar_pool_snippets_parser.set_defaults(handler=_handle_sidecar_pool_snippets)

    tui_parser = subparsers.add_parser("tui")
    tui_parser.add_argument("--config", default="config.yaml")
    tui_parser.add_argument("--candidates", default="candidates.json")
    tui_parser.add_argument("--probe-summary", default="state_data/probe_summary.json")
    tui_parser.add_argument("--passed-candidates", default="state_data/passed_candidates.json")
    tui_parser.add_argument("--selected-candidate", default="state_data/selected_candidate.json")
    tui_parser.add_argument("--pool-plan", default="state_data/sidecar_pool_plan.json")
    tui_parser.add_argument("--session", default="state_data/tui_session.json")
    tui_parser.add_argument("--output", default="state_data/selected_candidate.json")
    tui_parser.add_argument("--strategy", default="auto", choices=("auto", "manual", "geo_nearest", "geo-nearest", "region_hint", "region-hint", "first"))
    tui_parser.add_argument("--geo-cache", default="state_data/geo/candidate_geo_cache.json")
    tui_parser.add_argument("--host-geo", default="state_data/geo/host_geo.json")
    tui_parser.add_argument("--preferred-region-hint")
    tui_parser.add_argument("--prefer-geo", dest="prefer_geo", action="store_true", default=True)
    tui_parser.add_argument("--no-prefer-geo", dest="prefer_geo", action="store_false")
    tui_parser.set_defaults(handler=_handle_tui)

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
        source_subscription_hash = compute_artifact_hash(
            [
                {
                    "source_name": subscription.source_name,
                    "content": subscription.content,
                    "byte_count": subscription.byte_count,
                }
                for subscription in fetched
            ]
        )
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
            run_id=generate_run_id("fetch"),
            created_at=_utc_now_iso8601(),
            source_subscription_hash=source_subscription_hash,
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


def _handle_artifact_check(args: argparse.Namespace) -> int:
    """Check lineage consistency across local artifacts."""
    try:
        report = check_artifact_consistency(
            candidates_path=args.candidates,
            probe_summary_path=args.probe_summary,
            passed_candidates_path=args.passed_candidates,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    for key in (
        "candidates_present",
        "probe_summary_present",
        "passed_candidates_present",
        "candidates_hash",
        "probe_summary_source_candidates_match",
        "passed_candidates_source_candidates_match",
        "passed_candidates_source_probe_summary_match",
        "overall_consistent",
    ):
        print(f"{key}: {_render_optional_report_value(report.get(key))}")
    for warning in report.get("warnings", []):
        print(f"warning: {warning}")
    if report.get("overall_consistent") is False:
        return 1
    if report.get("overall_consistent") is None:
        return 2
    return 0


def _handle_artifact_explain_probe(args: argparse.Namespace) -> int:
    """Explain probe outcomes by redacted label or candidate ID."""
    try:
        payload = load_artifact_payload(args.probe_summary)
        explanation = build_probe_explanation(
            payload,
            label_regex=args.label_regex,
            candidate_id=args.candidate_id,
            protocol=args.protocol,
            error_category=args.error_category,
            marker=args.marker,
        )
    except (FileNotFoundError, ValueError, json.JSONDecodeError, re.error) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True))
    return 0


def _handle_select_list(args: argparse.Namespace) -> int:
    """Render one redacted candidate catalog from a local payload."""
    try:
        payload = load_candidate_payload(args.candidates)
        catalog = build_candidate_catalog(payload)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    _print_lineage_warning_for_payload(payload)
    if args.json:
        print(json.dumps(catalog_to_dicts(catalog), indent=2, ensure_ascii=False, sort_keys=True))
    else:
        print(format_candidate_catalog_table(catalog, include_label=not args.no_label))
    return 0


def _handle_select_choose(args: argparse.Namespace) -> int:
    """Choose one candidate and write a sensitive selected-candidate artifact."""
    try:
        payload = load_candidate_payload(args.candidates)
        _print_lineage_warning_for_payload(payload)
        candidate, probe, decision = select_candidate_with_policy(
            payload,
            _build_selection_policy_options(args),
        )
        record = _resolve_selection_record_for_artifact(
            payload,
            decision.selected_candidate_id,
            decision.selected_index,
        )
        artifact = build_selected_candidate_artifact(
            record,
            selection_method="candidate_id" if decision.method.startswith("manual:candidate_id") else "index",
        )
        artifact.update(
            {
                "artifact_type": "selected_candidate",
                "run_id": generate_run_id("select"),
                "created_at": _utc_now_iso8601(),
                "source_passed_candidates_hash": compute_artifact_hash(payload),
                "source_passed_candidates_run_id": payload.get("run_id"),
                "source_candidates_hash": payload.get("source_candidates_hash"),
                "source_probe_summary_hash": payload.get("source_probe_summary_hash"),
            }
        )
        write_selected_candidate_artifact(args.output, artifact)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Selected Scholar candidate.")
    print(f"selected_candidate_id: {decision.selected_candidate_id}")
    print(f"selected_index: {decision.selected_index}")
    print(f"selection_method: {decision.method}")
    print(f"reason: {decision.reason}")
    if decision.selected_label:
        print(f"selected_label: {decision.selected_label}")
    if decision.selected_region_hint:
        print(f"selected_region_hint: {decision.selected_region_hint}")
    if decision.geo_distance_km is not None:
        print(f"geo_distance_km: {decision.geo_distance_km:.2f}")
    print(f"output_path: {args.output}")
    print(f"candidate_protocol: {decision.candidate_protocol}")
    return 0


def _handle_select_explain(args: argparse.Namespace) -> int:
    """Explain the redacted selection policy decision."""
    try:
        payload = load_candidate_payload(args.candidates)
        _print_lineage_warning_for_payload(payload)
        explanation = explain_selection_policy(payload, _build_selection_policy_options(args))
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(explanation, indent=2, ensure_ascii=False, sort_keys=True))
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
        _validate_non_negative_int(args.transport_retry_count, "transport-retry-count")
        _validate_non_negative_float(args.transport_retry_backoff, "transport-retry-backoff")
        _validate_non_negative_int(args.hysteria2_warmup_attempts, "hysteria2-warmup-attempts")
        _validate_runtime_config_name(args.runtime_config_name)
        _validate_distinct_output_paths(args.summary_output, args.passed_candidates_output)

        config = load_config(args.config)
        _require_network_probe_opt_in(config.probe.allow_network_probe, args.allow_network_probe)
        source_candidates_payload = load_candidate_payload(args.candidates)
        loaded_candidates = load_candidates(args.candidates)
        candidates, filtered_out_count = _filter_candidates_for_cli(loaded_candidates, config.filters)
        candidate_options = CandidateProbeOptions(
            query=args.query,
            startup_timeout_seconds=args.startup_timeout,
            request_timeout_seconds=(
                config.probe.timeout_seconds if args.request_timeout is None else args.request_timeout
            ),
            xray_test_timeout_seconds=args.xray_test_timeout,
            transport_retry_count=args.transport_retry_count,
            transport_retry_backoff_seconds=args.transport_retry_backoff,
            hysteria2_warmup_attempts=args.hysteria2_warmup_attempts,
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
            source_candidates_payload=source_candidates_payload,
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


def _handle_geo_db_info(args: argparse.Namespace) -> int:
    """Inspect one local Geo database file without parsing it."""
    info = inspect_geo_database(args.geo_db)
    print("Geo database:")
    print(f"path: {info.path}")
    print(f"exists: {'true' if info.exists else 'false'}")
    print(f"readable: {'true' if info.readable else 'false'}")
    print(f"size_bytes: {'' if info.size_bytes is None else info.size_bytes}")
    print(f"format_hint: {info.format_hint or ''}")
    if info.error:
        print(f"error: {info.error}")
    return 0 if info.exists and info.readable else 1


def _handle_geo_cache_inspect(args: argparse.Namespace) -> int:
    """Inspect one local candidate Geo cache summary."""
    try:
        records = load_candidate_geo_cache(args.geo_cache)
        summary = summarize_candidate_geo_cache(records)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Candidate Geo cache:")
    print(f"schema_version: {summary.schema_version}")
    print(f"record_count: {summary.record_count}")
    print(f"endpoint_geo_count: {summary.endpoint_geo_count}")
    print(f"egress_geo_count: {summary.egress_geo_count}")
    print(f"manual_count: {summary.manual_count}")
    print(f"expired_count: {summary.expired_count}")
    print(f"missing_coordinates_count: {summary.missing_coordinates_count}")
    return 0


def _handle_geo_refresh_plan(args: argparse.Namespace) -> int:
    """Build one dry-run Geo refresh plan without DB or network access."""
    try:
        payload = load_candidate_payload(args.candidates)
        candidate_geo = load_candidate_geo_cache(args.geo_cache)
        plan = build_geo_refresh_plan(
            payload,
            candidate_geo,
            refresh_expired=args.refresh_expired,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    print("Geo refresh plan:")
    print(f"candidate_count: {plan.candidate_count}")
    print(f"cached_count: {plan.cached_count}")
    print(f"missing_count: {plan.missing_count}")
    print(f"expired_count: {plan.expired_count}")
    print(f"would_refresh_count: {plan.would_refresh_count}")
    print(f"mode: {plan.mode}")
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
        record = _resolve_candidate_record_from_args(args)
        options = _build_sidecar_options(args)
        summary = prepare_sidecar_runtime(
            candidate=record.candidate,
            xray_config=config.xray,
            options=options,
            candidate_id=record.candidate_id,
        )
    except (ConfigError, FileNotFoundError, ValueError, OSError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Prepared Scholar sidecar runtime.")
    print(f"candidate_id: {summary.candidate_id}")
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
        record = _resolve_candidate_record_from_args(args)
        options = _build_sidecar_options(args)
        prepared = prepare_sidecar_runtime(
            candidate=record.candidate,
            xray_config=config.xray,
            options=options,
            candidate_id=record.candidate_id,
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
    print(f"candidate_id: {summary.candidate_id}")
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
        _print_lineage_warning_for_selected_candidate_or_candidates(args)
        record = _resolve_candidate_record_from_args(args)
        paths = stage_systemd_sidecar_files(
            candidate=record.candidate,
            candidate_id=record.candidate_id,
            xray_config=config.xray,
            options=options,
            source_xray_binary_path=args.source_xray_binary,
            skip_xray_binary_copy=args.skip_xray_binary_copy,
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
    print(f"candidate_id: {record.candidate_id}")
    print(f"candidate_protocol: {record.candidate.protocol}")
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
    user_ok, user_messages = summarize_system_user_results(user_results)
    install_ok, install_messages = summarize_command_results(install_results)
    messages = [*user_messages, *install_messages]
    if messages:
        for message in messages:
            print(f"Error: {message}", file=sys.stderr)
        return 1
    return 0 if user_ok and install_ok else 1


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


def _handle_sidecar_service_validate(args: argparse.Namespace) -> int:
    """Validate one running production sidecar without mutating service state."""
    try:
        if args.listen_port <= 0:
            raise ValueError("listen-port must be greater than 0.")
        _validate_positive_float(args.request_timeout, "request-timeout")
        active_result = run_systemctl("is-active", args.unit_name)
        enabled_result = run_systemctl("is-enabled", args.unit_name)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    socks_tcp_connect = _check_tcp_connect(args.listen_host, args.listen_port, args.request_timeout)
    home = probe_http_via_socks(
        build_scholar_home_target(),
        SocksEndpoint(args.listen_host, args.listen_port),
        args.request_timeout,
    )
    query = probe_http_via_socks(
        build_scholar_query_target(args.query),
        SocksEndpoint(args.listen_host, args.listen_port),
        args.request_timeout,
    )
    decision = classify_scholar_access(home, query)

    service_active = active_result.ok and (active_result.stdout.strip() == "active" or active_result.returncode == 0)
    service_enabled = enabled_result.ok and enabled_result.stdout.strip() == "enabled"

    print(f"service_active: {str(service_active).lower()}")
    print(f"service_enabled: {str(service_enabled).lower()}")
    print(f"socks_tcp_connect: {str(socks_tcp_connect).lower()}")
    print(f"scholar_stage: {decision.stage}")
    print(f"scholar_passed: {str(decision.passed).lower()}")
    print(f"home_status: {home.status_code}")
    print(f"query_status: {query.status_code}")
    return 0 if service_active and service_enabled and socks_tcp_connect and decision.passed else 1


def _handle_sidecar_pool_plan(args: argparse.Namespace) -> int:
    """Build and write one redacted single-Xray sidecar pool plan."""
    try:
        payload = load_candidate_payload(args.candidates)
        plan = build_sidecar_pool_plan(
            payload,
            candidate_ids=args.candidate_ids,
            max_count=args.max_count,
            listen_host=args.listen_host,
            base_port=args.base_port,
        )
        write_pool_plan(args.output, plan)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Planned Scholar sidecar pool.")
    print(f"output_path: {args.output}")
    print(f"entry_count: {plan.count}")
    print(f"listen_host: {plan.listen_host}")
    print(f"base_port: {plan.base_port}")
    print(f"ports: {','.join(str(entry.listen_port) for entry in plan.entries)}")
    return 0


def _handle_sidecar_pool_check_ports(args: argparse.Namespace) -> int:
    """Check local availability for every port in one pool plan."""
    try:
        plan = load_pool_plan(args.plan)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    availability = check_pool_ports_available(plan)
    for entry in plan.entries:
        available = availability.get(entry.pool_index, False)
        print(f"pool_index: {entry.pool_index} listen_port: {entry.listen_port} available: {str(available).lower()}")
    return 0 if all(availability.values()) else 1


def _handle_sidecar_pool_stage(args: argparse.Namespace) -> int:
    """Stage one sensitive single-Xray pool runtime without installing the unit."""
    try:
        options = _build_systemd_sidecar_options(args)
        if _service_paths_require_root(options) and os.geteuid() != 0:
            raise PermissionError(
                "pool stage requires root for /opt, /etc, or /var targets; use root or custom paths."
            )
        config = load_config(args.config)
        payload = load_candidate_payload(args.candidates)
        _print_lineage_warning_for_payload(payload)
        plan = load_pool_plan(args.plan)
        paths = stage_single_xray_pool_files(
            payload=payload,
            plan=plan,
            xray_config=config.xray,
            options=options,
            source_xray_binary_path=args.source_xray_binary,
            skip_xray_binary_copy=args.skip_xray_binary_copy,
            allow_port_conflict=args.allow_port_conflict,
        )
    except (ConfigError, FileNotFoundError, PermissionError, ValueError, OSError, LookupError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print("Staged Scholar single-Xray sidecar pool.")
    print(f"xray_binary_path: {paths.xray_binary_path}")
    print(f"runtime_config_path: {paths.runtime_config_path}")
    print(f"metadata_path: {paths.metadata_path}")
    print(f"entry_count: {plan.count}")
    print("staged: true")
    return 0


def _handle_sidecar_pool_validate(args: argparse.Namespace) -> int:
    """Validate one running multi-port sidecar pool."""
    try:
        _validate_positive_float(args.request_timeout, "request-timeout")
        plan = load_pool_plan(args.plan)
        results = validate_pool_sidecar(
            plan,
            query=args.query,
            request_timeout=args.request_timeout,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(results, indent=2, ensure_ascii=False, sort_keys=True))
    return 0 if all(bool(result.get("passed")) for result in results) else 1


def _handle_sidecar_pool_snippets(args: argparse.Namespace) -> int:
    """Render downstream SOCKS snippets for a pool plan."""
    try:
        plan = load_pool_plan(args.plan)
        snippets = build_pool_socks_outbound_snippets(plan)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(snippets, indent=2, ensure_ascii=False, sort_keys=True))
    else:
        for snippet in snippets:
            server = snippet["settings"]["servers"][0]
            print(
                f"tag: {snippet['tag']} protocol: {snippet['protocol']} "
                f"address: {server['address']} port: {server['port']}"
            )
    return 0


def _handle_tui(args: argparse.Namespace) -> int:
    """Run the optional Textual TUI when installed."""
    try:
        from scholar_outbound_manager.tui.app import main as tui_main
    except ModuleNotFoundError as exc:
        if exc.name != "textual":
            raise
        print(
            'Textual TUI is not installed. Install with:\npip install "ScholarOutboundManager[tui]"',
            file=sys.stderr,
        )
        return 1
    tui_argv = [
        "--config",
        args.config,
        "--candidates",
        args.candidates,
        "--probe-summary",
        args.probe_summary,
        "--passed-candidates",
        args.passed_candidates,
        "--selected-candidate",
        args.selected_candidate,
        "--pool-plan",
        args.pool_plan,
        "--session",
        args.session,
        "--output",
        args.output,
        "--strategy",
        args.strategy,
        "--geo-cache",
        args.geo_cache,
        "--host-geo",
        args.host_geo,
        "--prefer-geo" if args.prefer_geo else "--no-prefer-geo",
    ]
    if args.preferred_region_hint:
        tui_argv.extend(["--preferred-region-hint", args.preferred_region_hint])
    return int(tui_main(tui_argv))


def _check_tcp_connect(host: str, port: int, timeout_seconds: float) -> bool:
    """Return whether a TCP connection to the SOCKS endpoint succeeds."""
    try:
        with socket.create_connection((host, port), timeout=timeout_seconds):
            return True
    except OSError:
        return False


def _print_lineage_warning_for_payload(payload: dict[str, object]) -> None:
    """Print one generic lineage warning when the payload lacks chain metadata."""
    warning = summarize_lineage_warning(payload)
    if warning:
        print(warning, file=sys.stderr)


def _print_lineage_warning_for_selected_candidate_or_candidates(args: argparse.Namespace) -> None:
    """Print lineage warnings for selected-candidate or candidates artifacts."""
    selected_candidate_path = getattr(args, "selected_candidate", None)
    if selected_candidate_path:
        _print_lineage_warning_for_payload(load_artifact_payload(selected_candidate_path))
        return
    candidates_path = getattr(args, "candidates", None)
    if candidates_path:
        _print_lineage_warning_for_payload(load_candidate_payload(candidates_path))


def _render_optional_report_value(value: object) -> str:
    """Render one optional artifact-check value."""
    if value is True:
        return "true"
    if value is False:
        return "false"
    if value is None:
        return "unknown"
    return str(value)


def _resolve_selection_record_for_artifact(
    payload: dict[str, object],
    candidate_id: str,
    candidate_index: int,
):
    """Resolve one record for artifact writing from the policy decision."""
    try:
        return select_candidate_by_id(payload, candidate_id)
    except ValueError:
        return select_candidate_by_index(payload, candidate_index)


def _resolve_candidate_record_from_args(args: argparse.Namespace):
    """Resolve one selected candidate record from mutually exclusive CLI args."""
    selection_method, selection_value = _resolve_candidate_selection_mode(
        candidate_id=getattr(args, "candidate_id", None),
        candidate_index=getattr(args, "candidate_index", None),
        selected_candidate=getattr(args, "selected_candidate", None),
    )
    if selection_method == "selected_candidate":
        return load_selected_candidate_artifact(str(selection_value))

    candidates_path = getattr(args, "candidates", None)
    if not candidates_path:
        raise ValueError("--candidates is required unless --selected-candidate is used.")
    payload = load_candidate_payload(candidates_path)
    if selection_method == "candidate_id":
        return select_candidate_by_id(payload, str(selection_value))
    return select_candidate_by_index(payload, int(selection_value))


def _resolve_candidate_selection_mode(
    *,
    candidate_id: str | None,
    candidate_index: int | None,
    selected_candidate: str | None,
) -> tuple[str, str | int]:
    """Resolve one mutually exclusive candidate selection mode."""
    provided = [
        ("selected_candidate", selected_candidate),
        ("candidate_id", candidate_id),
        ("index", candidate_index),
    ]
    active = [(name, value) for name, value in provided if value is not None]
    if len(active) > 1:
        raise ValueError(
            "--selected-candidate, --candidate-id, and --candidate-index are mutually exclusive."
        )
    if not active:
        return "index", 0
    return active[0]


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
    parser.add_argument("--candidates")
    _add_candidate_selection_arguments(parser)
    parser.add_argument("--listen-host", default="127.0.0.1")
    parser.add_argument("--listen-port", type=int, default=19080)
    parser.add_argument("--runtime-config-name", default="scholar_sidecar_runtime.json")


def _add_candidate_selection_arguments(parser: argparse.ArgumentParser) -> None:
    """Add mutually exclusive candidate selection arguments."""
    parser.add_argument("--candidate-id")
    parser.add_argument("--candidate-index", type=int)
    parser.add_argument("--selected-candidate")


def _build_selection_policy_options(args: argparse.Namespace) -> SelectionPolicyOptions:
    """Build selection policy options from CLI args."""
    return SelectionPolicyOptions(
        preferred_candidate_id=getattr(args, "candidate_id", None),
        preferred_candidate_index=getattr(args, "candidate_index", None),
        preferred_region_hint=getattr(args, "preferred_region_hint", None),
        selected_candidate_path=getattr(args, "selected_candidate", None),
        strategy=getattr(args, "strategy", "auto"),
        geo_cache_path=getattr(args, "geo_cache", "state_data/geo/candidate_geo_cache.json"),
        host_geo_path=getattr(args, "host_geo", "state_data/geo/host_geo.json"),
        prefer_geo=getattr(args, "prefer_geo", True),
        prefer_region_hint=bool(getattr(args, "preferred_region_hint", None)),
        fallback_to_first=True,
    )


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


def _utc_now_iso8601() -> str:
    """Return one UTC timestamp with a Z suffix."""
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


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


def _validate_non_negative_int(value: int, name: str) -> None:
    """Validate that an integer argument is non-negative."""
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0.")


def _validate_non_negative_float(value: float, name: str) -> None:
    """Validate that a float argument is non-negative."""
    if value < 0:
        raise ValueError(f"{name} must be greater than or equal to 0.")


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
