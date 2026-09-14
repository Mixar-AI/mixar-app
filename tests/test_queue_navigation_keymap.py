# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Queue tab's addon keyconfig must bind the same pan event C handles.

A trackpad two-finger scroll arrives as the C event MOUSEPAN, whose
KeyMapItem.type identifier in Blender 5.2 is 'TRACKPADPAN' (5.0 called it
'MOUSEPAN'). Binding an identifier the enum does not know raises TypeError
mid-register(), so wheel/page/home items never land and the gesture falls
through to transcript scrolling.
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


def test_queue_addon_keymap_binds_the_52_trackpad_pan_identifier():
    keymap = PY_KEYMAP.read_text(encoding="utf-8")
    native = CC_NAV.read_text(encoding="utf-8")
    assert "event->type == MOUSEPAN" in native
    assert "'TRACKPADPAN'" in keymap
    assert "'MOUSEPAN'" not in keymap, (
        "5.2 removed MOUSEPAN from the Python event enum; binding it raises"
    )
