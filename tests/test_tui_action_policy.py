"""Tests for the TUI action risk policy."""

from __future__ import annotations

from scholar_outbound_manager.tui.action_policy import ActionRiskLevel
from scholar_outbound_manager.tui.action_policy import get_action_policy


def test_routine_and_passive_actions_do_not_require_confirmation() -> None:
    assert get_action_policy("fetch").requires_confirmation is False
    assert get_action_policy("probe").requires_confirmation is False
    assert get_action_policy("retest_failed").requires_confirmation is False
    assert get_action_policy("artifact_check").requires_confirmation is False
    assert get_action_policy("service_validate").requires_confirmation is False


def test_destructive_actions_require_confirmation() -> None:
    assert get_action_policy("sidecar_stage").requires_confirmation is True
    assert get_action_policy("service_start").requires_confirmation is True
    assert get_action_policy("service_stop").requires_confirmation is True
    assert get_action_policy("service_restart").requires_confirmation is True
    assert get_action_policy("rollback_snapshot").requires_confirmation is True


def test_action_policy_exposes_operator_risk_shape() -> None:
    fetch = get_action_policy("fetch")
    restart = get_action_policy("service_restart")

    assert fetch.risk_level is ActionRiskLevel.ROUTINE
    assert fetch.network_access is True
    assert fetch.creates_snapshot is True
    assert restart.risk_level is ActionRiskLevel.DESTRUCTIVE
    assert restart.systemd_access is True
    assert restart.mutates_service is True
