# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A turn-checkpoint snapshot copy must not close the island and pill.

Every fresh Send writes a ``copy=True`` snapshot from a click inside the
island; closing and re-creating both OS windows for it made the clicked
window vanish under the cursor. ``keep_windows_for_snapshot`` makes
``on_save_pre`` skip the purge for that save only; user saves keep it.
"""

import importlib
import sys
from types import ModuleType
from unittest.mock import MagicMock

import pytest


@pytest.fixture
def lifecycle(monkeypatch):
    for name in (
        "mixar.modules.agent_bubble.core.pill_icons",
    ):
        module = ModuleType(name)
        module.refresh = MagicMock()
        monkeypatch.setitem(sys.modules, name, module)
    sys.modules.pop("mixar.modules.agent_bubble.core.bubble_lifecycle", None)
    module = importlib.import_module("mixar.modules.agent_bubble.core.bubble_lifecycle")
    monkeypatch.setattr(module, "close_restored_agent_bubble_windows", MagicMock(return_value=2))
    module._st.closed_for_save = False
    module._st.snapshot_save_depth = 0
    return module


def test_snapshot_save_keeps_the_windows(lifecycle):
    with lifecycle.keep_windows_for_snapshot():
        assert lifecycle._st.snapshot_save_depth == 1
        lifecycle.on_save_pre("/tmp/x.tmp.mixar")
    assert not lifecycle.close_restored_agent_bubble_windows.called
    assert lifecycle._st.closed_for_save is False
    assert lifecycle._st.snapshot_save_depth == 0


def test_user_save_still_purges_the_windows(lifecycle):
    lifecycle.on_save_pre("/tmp/project.mixar")
    assert lifecycle.close_restored_agent_bubble_windows.called
    assert lifecycle._st.closed_for_save is True


def test_guard_depth_survives_a_failing_save(lifecycle):
    with pytest.raises(RuntimeError):
        with lifecycle.keep_windows_for_snapshot():
            raise RuntimeError("save failed")
    assert lifecycle._st.snapshot_save_depth == 0
