# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Feedback contracts of the agent island's generation panes.

The island is its own always-on-top window: no status bar, no Info editor. So
the two things the moodboard N-panel leans on are both invisible here — the
per-tab ``scene.mixie_*_is_generating`` flags (which several enqueue paths
never set at all) and ``self.report()``. Pressing Generate therefore produced
NO feedback whatsoever, even when the click was refused.

The message line that fixes that reads a DEDICATED channel written only by
the panes' own Generate dispatcher, never Blender's global report list: that
list carries the whole app's activity, Mixar's own agent running sandboxed
Blender scripts included, so the pane painted unrelated bpy script output
above the user's prompt.

Mostly source-level, like the rest of the island's C++ surface (see
``test_agent_bubble_panes.py``): these are draw rules whose C++ half has no
importable Python counterpart. The channel's Python half IS importable and is
exercised directly.
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
PY = ROOT / "src/scripts/mixar/modules"

if str(ROOT / "src/scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "src/scripts"))

FEEDBACK = (CPP / "agent_ui_pane_kit_feedback.cc").read_text(encoding="utf-8")
KIT_HH = (CPP / "agent_ui_pane_kit.hh").read_text(encoding="utf-8")
QUEUE_CC = (CPP / "agent_ui_queue_data.cc").read_text(encoding="utf-8")
CMAKE = (CPP / "CMakeLists.txt").read_text(encoding="utf-8")

CHANNEL_PY = PY / "agent_bubble/ui/properties/pane_message_props.py"
DISPATCH_PY = PY / "moodboard/ui/operators/prompt_generate_ops.py"
CHANNEL_SRC = CHANNEL_PY.read_text(encoding="utf-8")
DISPATCH_SRC = DISPATCH_PY.read_text(encoding="utf-8")

#: The one channel, named in both languages.
CHANNEL_PROPS = (
    "mixar_pane_message",
    "mixar_pane_message_level",
    "mixar_pane_message_serial",
)

from mixar.modules.agent_bubble.ui.properties import (  # noqa: E402
    pane_message_props as CHANNEL,
)

# Every translation unit a pane's own drawing lives in. The Splat pane is
# split across state, controls and geometry, so all three count as "the
# Splat pane" for these contracts.
PANE_SOURCES = {
    name: (CPP / name).read_text(encoding="utf-8")
    for name in (
        "agent_ui_tab3d.cc",
        "agent_ui_tabmedia.cc",
        "agent_ui_tabsplat.cc",
        "agent_ui_tabsplat_paint.cc",
        "agent_ui_tabsplat_state.cc",
    )
}
PANES = {
    "3D": ("agent_ui_tab3d.cc",),
    "Media": ("agent_ui_tabmedia.cc",),
    "Splat": ("agent_ui_tabsplat.cc", "agent_ui_tabsplat_paint.cc", "agent_ui_tabsplat_state.cc"),
}

_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_LINE_COMMENT = re.compile(r"//[^\n]*")


def _code(source: str) -> str:
    """`source` with comments removed — these tests are about what RUNS.

    Every rule below is also *described* in a comment somewhere near the code
    that obeys it, so a naive substring search matches the prose that explains
    the old behaviour just as happily as the old behaviour itself.
    """
    return _LINE_COMMENT.sub("", _BLOCK_COMMENT.sub("", source))


def _pane_code(pane: str) -> str:
    return "\n".join(_code(PANE_SOURCES[name]) for name in PANES[pane])
