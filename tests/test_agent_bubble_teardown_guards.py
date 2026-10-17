# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island survives its windows coming and going.

* ``window.screen`` is None while a window is being created or torn down,
  and the island lives in its own wmWindows — so the repaint loops in its
  property updates and operators run exactly then. An unguarded
  ``window.screen.areas`` raised AttributeError inside bpy's update
  machinery, where it neither cancels the change nor names the culprit.
* File load frees the bubble through ``ED_agent_bubble_window_freed`` alone
  (``wm_close_and_free``), never ``ED_agent_bubble_windows_closed``, so a
  latch reset only in the latter survives into the recreated bubble.
* A generation's .blend is never rewritten, so a memoised failed stat
  blanked its age and sorted it last for the whole session.

C++ contracts are source-level, like the rest of the island's.
"""

import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / "src/source/blender/editors/space_agent_bubble"
BUBBLE_CC = (CPP / "space_agent_bubble.cc").read_text(encoding="utf-8")
READ_CC = (CPP / "agent_ui_generations_read.cc").read_text(encoding="utf-8")
MODULE = ROOT / "src/scripts/mixar/modules/agent_bubble"


def _body(source: str, signature_start: str) -> str:
    start = source.index(signature_start)
    open_brace = source.index("{", start)
    depth = 0
    for i in range(open_brace, len(source)):
        if source[i] == "{":
            depth += 1
        elif source[i] == "}":
            depth -= 1
            if depth == 0:
                return source[start : i + 1]
    raise AssertionError(f"unbalanced body after {signature_start!r}")


# ---------------------------------------------------------------------------
# 1. A window without a screen is skipped, not dereferenced
# ---------------------------------------------------------------------------


def test_no_agent_bubble_code_reaches_through_window_screen_unguarded():
    offenders = []
    for path in sorted(MODULE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "areas"
                and isinstance(node.value, ast.Attribute)
                and node.value.attr == "screen"
            ):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert offenders == [], (
        "bind `screen = window.screen` and skip None before `.areas`: "
        + ", ".join(offenders)
    )


class _Area:
    def __init__(self, type_):
        self.type = type_
        self.regions = []
        self.redraws = 0

    def tag_redraw(self):
        self.redraws += 1


def _wm_with_a_screenless_window():
    bubble = _Area("AGENT_BUBBLE")
    windows = [
        SimpleNamespace(screen=None),
        SimpleNamespace(screen=SimpleNamespace(areas=[bubble])),
    ]
    return SimpleNamespace(windows=windows), bubble


@pytest.mark.parametrize(
    "module",
    [
        "mixar.modules.agent_bubble.ui.properties.queue_navigation_props",
        "mixar.modules.agent_bubble.ui.properties.reference_column_props",
    ],
)
def test_scroll_updates_repaint_past_a_screenless_window(module):
    import importlib

    redraw = importlib.import_module(module)._redraw
    wm, bubble = _wm_with_a_screenless_window()
    redraw(None, SimpleNamespace(window_manager=wm))
    assert bubble.redraws == 1


# ---------------------------------------------------------------------------
# 2. File load resets the island's own latches
# ---------------------------------------------------------------------------


def test_window_freed_resets_the_chat_grow_latch_like_windows_closed():
    closed = _body(BUBBLE_CC, "void ED_agent_bubble_windows_closed()")
    freed = _body(BUBBLE_CC, "void ED_agent_bubble_window_freed(const void *ghostwin)")
    assert "g_bubble_grown_for_chat = false;" in closed
    bubble_branch = freed[freed.index("if (ghostwin == g_bubble_ghostwin) {") :]
    bubble_branch = bubble_branch[: bubble_branch.index("}") + 1]
    assert "g_bubble_grown_for_chat = false;" in bubble_branch


def test_header_draw_has_no_unreachable_tail():
    body = _body(
        BUBBLE_CC, "void agent_bubble_header_region_draw(const bContext *C, ARegion *region)"
    )
    assert "ED_region_header(" not in body


# ---------------------------------------------------------------------------
# 3. Only a successful stat is memoised
# ---------------------------------------------------------------------------


def test_a_failed_stat_returns_before_it_is_cached():
    body = _body(READ_CC, "double gen_blend_mtime(const char *path)")
    failed = body.index("if (BLI_stat(path, &st) != 0) {")
    early_return = body.index("return 0.0;", failed)
    assert early_return < body.index("cache.add_new(")
    assert body.count("cache.add_new(") == 1
