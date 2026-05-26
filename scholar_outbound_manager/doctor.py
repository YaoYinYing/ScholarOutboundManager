"""Local-only preflight checks for ScholarOutboundManager."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from scholar_outbound_manager.config import ConfigError
from scholar_outbound_manager.config import load_config
from scholar_outbound_manager.io import load_candidate_bundle
from scholar_outbound_manager.models import AppConfig
from scholar_outbound_manager.models import CandidateProxy
from scholar_outbound_manager.models import ProbeResult
from scholar_outbound_manager.parsers.filtering import filter_candidates

_GITIGNORE_REQUIRED_ENTRIES = (
    "config.yaml",
    "candidates.json",
    "passed_candidates.json",
    "probe_summary.json",
    "generated/",
    "state_data/",
    ".runtime/",
    ".env",
)


@dataclass(frozen=True)
class DoctorCheck:
    """Represent one doctor check outcome."""

    name: str
    status: str
    message: str

    def __post_init__(self) -> None:
        """Validate the status value."""
        if self.status not in {"ok", "warn", "error"}:
            raise ValueError("DoctorCheck.status must be one of: ok, warn, error.")


@dataclass(frozen=True)
class DoctorReport:
    """Represent the complete doctor report."""

    checks: list[DoctorCheck]

    @property
    def ok_count(self) -> int:
        """Count successful checks."""
        return sum(1 for check in self.checks if check.status == "ok")

    @property
    def warn_count(self) -> int:
        """Count warning checks."""
        return sum(1 for check in self.checks if check.status == "warn")

    @property
    def error_count(self) -> int:
        """Count failing checks."""
        return sum(1 for check in self.checks if check.status == "error")

    @property
    def exit_code(self) -> int:
        """Return the doctor command exit code."""
        return 1 if self.error_count > 0 else 0


def build_doctor_report(
    config_path: str | Path,
    candidates_path: str | Path | None = None,
    require_network_probe_ready: bool = False,
    require_passed_candidates: bool = False,
) -> DoctorReport:
    """Build one local-only doctor report from config and optional candidates."""
    checks: list[DoctorCheck] = []
    config: AppConfig | None = None

    try:
        config = load_config(config_path)
    except (ConfigError, FileNotFoundError, ValueError) as exc:
        checks.append(DoctorCheck("config_load", "error", str(exc)))
        checks.extend(_gitignore_checks())
        return DoctorReport(checks)

    checks.append(DoctorCheck("config_load", "ok", f"Loaded config from {Path(config_path)}."))
    checks.append(_probe_safety_gate_check(config.probe.allow_network_probe, require_network_probe_ready))
    checks.append(_xray_binary_path_check(config.xray.binary_path))
    checks.append(_runtime_dir_check(config.xray.runtime_dir))
    checks.extend(_output_path_checks(config))
    checks.extend(_routing_checks(config))
    checks.extend(_generation_checks(config))

    if candidates_path is not None:
        checks.extend(
            _candidate_checks(
                config=config,
                candidates_path=candidates_path,
                require_passed_candidates=require_passed_candidates,
            )
        )

    checks.extend(_gitignore_checks())
    return DoctorReport(checks)


def format_doctor_report(report: DoctorReport) -> str:
    """Format a doctor report for CLI output."""
    lines = [
        "ScholarOutboundManager doctor report",
        f"ok: {report.ok_count}",
        f"warn: {report.warn_count}",
        f"error: {report.error_count}",
    ]
    for check in report.checks:
        lines.append(f"[{check.status.upper()}] {check.name}: {check.message}")
    return "\n".join(lines)


def _probe_safety_gate_check(
    allow_network_probe: bool,
    require_network_probe_ready: bool,
) -> DoctorCheck:
    """Evaluate the live network probe safety gate."""
    if not allow_network_probe and require_network_probe_ready:
        return DoctorCheck(
            "probe_safety_gate",
            "error",
            "Live probe is not ready: probe.allow_network_probe is false in config.",
        )
    if not allow_network_probe:
        return DoctorCheck(
            "probe_safety_gate",
            "warn",
            "Live probe is disabled by default because probe.allow_network_probe is false.",
        )
    return DoctorCheck(
        "probe_safety_gate",
        "ok",
        "probe.allow_network_probe is true. Live probing still requires --allow-network-probe at CLI.",
    )


def _xray_binary_path_check(binary_path: str) -> DoctorCheck:
    """Check the configured Xray binary path without executing it."""
    if not binary_path:
        return DoctorCheck("xray_binary_path", "error", "xray.binary_path is empty.")
    binary = Path(binary_path)
    if not binary.exists():
        return DoctorCheck("xray_binary_path", "warn", f"Xray binary path does not exist: {binary}.")
    if not binary.is_file():
        return DoctorCheck("xray_binary_path", "warn", f"Xray binary path is not a file: {binary}.")
    return DoctorCheck("xray_binary_path", "ok", f"Found Xray binary path: {binary}.")


def _runtime_dir_check(runtime_dir: str) -> DoctorCheck:
    """Check the configured runtime directory setting."""
    if not runtime_dir:
        return DoctorCheck("runtime_dir", "error", "xray.runtime_dir is empty.")
    return DoctorCheck("runtime_dir", "ok", f"Runtime directory is configured: {runtime_dir}.")


def _output_path_checks(config: AppConfig) -> list[DoctorCheck]:
    """Check output path settings."""
    checks: list[DoctorCheck] = []
    output_paths = {
        "outbounds_path": config.output.outbounds_path,
        "routes_path": config.output.routes_path,
        "manifest_path": config.output.manifest_path,
    }
    for name, value in output_paths.items():
        if not value:
            checks.append(DoctorCheck("output_paths", "error", f"output.{name} is empty."))
    if len({config.output.outbounds_path, config.output.routes_path, config.output.manifest_path}) != 3:
        checks.append(DoctorCheck("output_paths", "error", "output paths must be distinct."))
    if not checks:
        checks.append(DoctorCheck("output_paths", "ok", "Output paths are configured and distinct."))
    return checks


def _routing_checks(config: AppConfig) -> list[DoctorCheck]:
    """Check routing settings."""
    checks: list[DoctorCheck] = []
    if config.routing.mode == "dedicated_inbound":
        checks.append(DoctorCheck("routing_mode", "ok", "routing.mode is dedicated_inbound."))
    else:
        checks.append(DoctorCheck("routing_mode", "error", f"Unsupported routing.mode: {config.routing.mode}."))
    if config.routing.inbound_tags:
        checks.append(DoctorCheck("routing_inbound_tags", "ok", "routing.inbound_tags is not empty."))
    else:
        checks.append(DoctorCheck("routing_inbound_tags", "error", "routing.inbound_tags is empty."))
    if config.routing.fail_closed:
        checks.append(DoctorCheck("routing_fail_closed", "ok", "routing.fail_closed is enabled."))
    else:
        checks.append(
            DoctorCheck(
                "routing_fail_closed",
                "warn",
                "routing.fail_closed is false, so Scholar routing may not be fail-closed.",
            )
        )
    return checks


def _generation_checks(config: AppConfig) -> list[DoctorCheck]:
    """Check generation settings."""
    checks: list[DoctorCheck] = []
    if config.generation.max_passed_nodes > 0:
        checks.append(DoctorCheck("generation_max_passed_nodes", "ok", "generation.max_passed_nodes is positive."))
    else:
        checks.append(DoctorCheck("generation_max_passed_nodes", "error", "generation.max_passed_nodes must be greater than 0."))
    if config.generation.tag_prefix:
        checks.append(DoctorCheck("generation_tag_prefix", "ok", "generation.tag_prefix is configured."))
    else:
        checks.append(DoctorCheck("generation_tag_prefix", "error", "generation.tag_prefix is empty."))
    if config.generation.fallback_blackhole_tag:
        checks.append(DoctorCheck("generation_fallback_blackhole_tag", "ok", "generation.fallback_blackhole_tag is configured."))
    else:
        checks.append(
            DoctorCheck(
                "generation_fallback_blackhole_tag",
                "error",
                "generation.fallback_blackhole_tag is empty.",
            )
        )
    return checks


def _candidate_checks(
    config: AppConfig,
    candidates_path: str | Path,
    require_passed_candidates: bool,
) -> list[DoctorCheck]:
    """Check candidate bundle loading and filtering effects."""
    checks: list[DoctorCheck] = []
    try:
        bundle = load_candidate_bundle(candidates_path)
    except (FileNotFoundError, ValueError) as exc:
        checks.append(DoctorCheck("candidate_load", "error", str(exc)))
        return checks

    checks.append(DoctorCheck("candidate_load", "ok", f"Loaded candidate bundle from {Path(candidates_path)}."))
    filtered_candidates = filter_candidates(bundle.candidates, config.filters)
    filtered_probe_results = _filter_probe_results(bundle.candidates, bundle.probe_results, filtered_candidates)
    loaded_count = len(bundle.candidates)
    filtered_count = len(filtered_candidates)
    skipped_by_filter_count = loaded_count - filtered_count
    supported_count = sum(1 for candidate in filtered_candidates if candidate.supported)
    unsupported_count = filtered_count - supported_count
    with_probe_evidence_count = sum(1 for probe_result in filtered_probe_results if probe_result is not None)

    if loaded_count == 0:
        checks.append(DoctorCheck("candidate_counts", "error", "Loaded candidate bundle is empty."))
    elif filtered_count == 0:
        checks.append(
            DoctorCheck(
                "candidate_counts",
                "error",
                f"Candidate filters removed all entries. loaded={loaded_count}, filtered=0, skipped_by_filter={skipped_by_filter_count}.",
            )
        )
    else:
        candidate_status = "ok"
        if supported_count == 0 and require_passed_candidates:
            candidate_status = "error"
        elif supported_count == 0:
            candidate_status = "warn"
        checks.append(
            DoctorCheck(
                "candidate_counts",
                candidate_status,
                "loaded="
                f"{loaded_count}, filtered={filtered_count}, skipped_by_filter={skipped_by_filter_count}, "
                f"supported={supported_count}, unsupported={unsupported_count}, with_probe_evidence={with_probe_evidence_count}.",
            )
        )

    checks.append(
        DoctorCheck(
            "candidate_filters",
            "ok",
            f"Applied configured filters without exposing candidate names. loaded={loaded_count}, filtered={filtered_count}.",
        )
    )

    checks.extend(
        _passed_candidates_shape_checks(
            candidates_path=candidates_path,
            require_passed_candidates=require_passed_candidates,
            with_probe_evidence_count=with_probe_evidence_count,
        )
    )
    return checks


def _passed_candidates_shape_checks(
    candidates_path: str | Path,
    require_passed_candidates: bool,
    with_probe_evidence_count: int,
) -> list[DoctorCheck]:
    """Check whether the candidate file looks like a passed-candidates artifact."""
    checks: list[DoctorCheck] = []
    payload = _load_raw_json(candidates_path)
    if payload is None:
        return checks

    if isinstance(payload, dict):
        sensitive = payload.get("sensitive")
        candidates = payload.get("candidates")
    else:
        sensitive = None
        candidates = payload

    if sensitive is True:
        if isinstance(candidates, list) and all(
            isinstance(item, dict) and "candidate" in item for item in candidates
        ):
            checks.append(
                DoctorCheck(
                    "passed_candidates_shape",
                    "ok",
                    "Sensitive passed-candidates artifact uses nested candidate/probe entries.",
                )
            )
        else:
            checks.append(
                DoctorCheck(
                    "passed_candidates_shape",
                    "warn",
                    "Sensitive passed-candidates artifact does not use nested candidate/probe entries.",
                )
            )
    elif isinstance(payload, list) or (isinstance(payload, dict) and payload.get("candidates") is not None):
        checks.append(
            DoctorCheck(
                "passed_candidates_shape",
                "warn",
                "Candidate file looks like a plain candidate artifact with no embedded probe evidence.",
            )
        )

    if require_passed_candidates and with_probe_evidence_count == 0:
        checks.append(
            DoctorCheck(
                "passed_candidates_probe_evidence",
                "warn",
                "No probe evidence was found in the candidate artifact even though passed-candidates readiness was requested.",
            )
        )
    elif with_probe_evidence_count > 0:
        checks.append(
            DoctorCheck(
                "passed_candidates_probe_evidence",
                "ok",
                f"Found probe evidence for {with_probe_evidence_count} filtered candidates.",
            )
        )
    return checks


def _gitignore_checks() -> list[DoctorCheck]:
    """Check for local-sensitive ignore entries in the current working tree."""
    gitignore_path = Path.cwd() / ".gitignore"
    if not gitignore_path.exists():
        return [DoctorCheck("gitignore_safety", "warn", f"No .gitignore found at {gitignore_path}.")]
    gitignore_text = gitignore_path.read_text(encoding="utf-8")
    missing = [entry for entry in _GITIGNORE_REQUIRED_ENTRIES if entry not in gitignore_text]
    if missing:
        return [
            DoctorCheck(
                "gitignore_safety",
                "warn",
                "Missing .gitignore entries for sensitive local artifacts: " + ", ".join(missing) + ".",
            )
        ]
    return [DoctorCheck("gitignore_safety", "ok", "Sensitive local artifact patterns are present in .gitignore.")]


def _filter_probe_results(
    loaded_candidates: list[CandidateProxy],
    loaded_probe_results: list[ProbeResult | None],
    filtered_candidates: list[CandidateProxy],
) -> list[ProbeResult | None]:
    """Align optional probe evidence to the filtered candidate order."""
    if not loaded_probe_results:
        return []
    probe_by_candidate_id = {
        id(candidate): probe_result
        for candidate, probe_result in zip(loaded_candidates, loaded_probe_results)
    }
    return [probe_by_candidate_id.get(id(candidate)) for candidate in filtered_candidates]


def _load_raw_json(path: str | Path) -> object | None:
    """Load one raw JSON payload for shape inspection when available."""
    candidate_path = Path(path)
    try:
        raw_text = candidate_path.read_text(encoding="utf-8")
        return json.loads(raw_text)
    except (OSError, json.JSONDecodeError):
        return None
