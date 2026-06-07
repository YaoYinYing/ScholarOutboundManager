from __future__ import annotations

from scholar_outbound_manager.tui.effects import CreateSnapshot
from scholar_outbound_manager.tui.effects import RunFetch
from scholar_outbound_manager.tui.effects import RunProbe
from scholar_outbound_manager.tui.effects import SaveRouteDraft


def test_effects_are_hashable_value_objects() -> None:
    effects = {
        CreateSnapshot(reason="testing_probe"),
        RunFetch(),
        RunProbe(),
        SaveRouteDraft(entries=()),
    }

    assert CreateSnapshot(reason="testing_probe") in effects
    assert RunFetch() in effects
    assert len(effects) == 4
