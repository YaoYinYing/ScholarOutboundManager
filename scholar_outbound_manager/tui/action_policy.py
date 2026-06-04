"""Central action risk policy for the config-centered TUI."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ActionRiskLevel(str, Enum):
    """Classify one TUI action by operator risk."""

    PASSIVE = "passive"
    ROUTINE = "routine"
    DESTRUCTIVE = "destructive"


@dataclass(slots=True, frozen=True)
class ActionPolicy:
    """Describe the operator-facing risk contract for one action."""

    key: str
    risk_level: ActionRiskLevel
    requires_confirmation: bool
    creates_snapshot: bool
    network_access: bool
    systemd_access: bool
    writes_artifact: bool
    mutates_service: bool
    can_cancel: bool
    user_facing_risk: str


_POLICIES: dict[str, ActionPolicy] = {
    "artifact_check": ActionPolicy(
        key="artifact_check",
        risk_level=ActionRiskLevel.PASSIVE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=False,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Read-only lineage check. Does not write artifacts or touch services.",
    ),
    "show_diff": ActionPolicy(
        key="show_diff",
        risk_level=ActionRiskLevel.PASSIVE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=False,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Read-only config diff. Sensitive values remain redacted.",
    ),
    "service_validate": ActionPolicy(
        key="service_validate",
        risk_level=ActionRiskLevel.PASSIVE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=True,
        systemd_access=True,
        writes_artifact=False,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Read-only validation of the managed sidecar. Does not modify production Xray/XrayR/x-ui.",
    ),
    "route_test_port": ActionPolicy(
        key="route_test_port",
        risk_level=ActionRiskLevel.PASSIVE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=False,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Read-only local port check. Does not mutate services or artifacts.",
    ),
    "fetch": ActionPolicy(
        key="fetch",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=True,
        network_access=True,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=True,
        user_facing_risk="Live network fetch. Writes local candidate artifacts under user_data_dir.",
    ),
    "probe": ActionPolicy(
        key="probe",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=True,
        network_access=True,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=True,
        user_facing_risk="Live node testing. Writes local probe and passed-candidate artifacts under user_data_dir.",
    ),
    "retest_failed": ActionPolicy(
        key="retest_failed",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=True,
        network_access=True,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=True,
        user_facing_risk="Retests failed nodes and rewrites local probe artifacts.",
    ),
    "config_save": ActionPolicy(
        key="config_save",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Writes config.yaml through the config transaction and undo journal.",
    ),
    "choose_selected_candidate": ActionPolicy(
        key="choose_selected_candidate",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=True,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Updates local selected route artifacts only. Does not touch the managed service.",
    ),
    "route_choose_node": ActionPolicy(
        key="route_choose_node",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=False,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Updates the local route draft only. Does not touch production services.",
    ),
    "select": ActionPolicy(
        key="select",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=True,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Writes one local selected-candidate artifact from the current passed set.",
    ),
    "create_snapshot": ActionPolicy(
        key="create_snapshot",
        risk_level=ActionRiskLevel.ROUTINE,
        requires_confirmation=False,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Creates one local artifact snapshot for recovery.",
    ),
    "sidecar_stage": ActionPolicy(
        key="sidecar_stage",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=True,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=True,
        can_cancel=False,
        user_facing_risk="Applies local route/runtime changes for the managed sidecar only.",
    ),
    "pool_stage": ActionPolicy(
        key="pool_stage",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=True,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=True,
        can_cancel=False,
        user_facing_risk="Applies local multi-route pool changes for the managed sidecar only.",
    ),
    "service_start": ActionPolicy(
        key="service_start",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=False,
        network_access=False,
        systemd_access=True,
        writes_artifact=False,
        mutates_service=True,
        can_cancel=False,
        user_facing_risk="Starts only the ScholarOutboundManager-managed sidecar service.",
    ),
    "service_stop": ActionPolicy(
        key="service_stop",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=False,
        network_access=False,
        systemd_access=True,
        writes_artifact=False,
        mutates_service=True,
        can_cancel=False,
        user_facing_risk="Stops only the ScholarOutboundManager-managed sidecar service.",
    ),
    "service_restart": ActionPolicy(
        key="service_restart",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=False,
        network_access=False,
        systemd_access=True,
        writes_artifact=False,
        mutates_service=True,
        can_cancel=False,
        user_facing_risk="Restarts only the ScholarOutboundManager-managed sidecar service.",
    ),
    "rollback_snapshot": ActionPolicy(
        key="rollback_snapshot",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=False,
        network_access=False,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=False,
        user_facing_risk="Restores local artifacts only. Does not undo network effects or restart the sidecar.",
    ),
    "xray_install_or_update": ActionPolicy(
        key="xray_install_or_update",
        risk_level=ActionRiskLevel.DESTRUCTIVE,
        requires_confirmation=True,
        creates_snapshot=False,
        network_access=True,
        systemd_access=False,
        writes_artifact=True,
        mutates_service=False,
        can_cancel=True,
        user_facing_risk="Downloads or updates local runtime binaries. Production services remain out of scope.",
    ),
}


def get_action_policy(action_key: str) -> ActionPolicy:
    """Return the configured policy for one action key."""

    try:
        return _POLICIES[action_key]
    except KeyError as exc:
        raise ValueError(f"Unknown action policy: {action_key}") from exc


__all__ = ["ActionPolicy", "ActionRiskLevel", "get_action_policy"]
