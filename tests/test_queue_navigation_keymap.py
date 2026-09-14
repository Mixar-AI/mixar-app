# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Queue tab's addon keyconfig must bind the same pan event C handles.

A trackpad two-finger scroll arrives as MOUSEPAN. Binding any other pan
type raises TypeError mid-register(), so wheel/page/home items never land
and the gesture falls through to transcript scrolling.
"""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY_KEYMAP = (
    ROOT / "src" / "scripts" / "mixar" / "modules" / "agent_bubble"
    / "ui" / "operators" / "queue_navigation.py"
)
CC_NAV = (
    ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble"
    / "agent_ui_queue_navigation.cc"
)


def test_queue_addon_keymap_binds_mousepan_not_a_trackpad_alias():
    keymap = PY_KEYMAP.read_text(encoding="utf-8")
    native = CC_NAV.read_text(encoding="utf-8")
    assert "event->type == MOUSEPAN" in native
    assert "'MOUSEPAN'" in keymap
    assert "TRACKPADPAN" not in keymap
