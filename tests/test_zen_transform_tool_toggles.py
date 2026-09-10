# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Zen Mode's Move / Rotate / Scale strip behaves like three toggles.

Blender has no "no tool" state: `wm.tool_set_by_id` activates a tool and
exactly one tool is active for the workspace at all times. A toggle click
therefore has to land on a DIFFERENT tool, and the design's answer is "the
one you came from" — the last non-transform tool the strip displaced, or
the panel's own `tool_fallback_id` when there is nothing remembered.

Both halves fail quietly when wrong rather than loudly: a strip that forgets
the user's select tool strands them in a transform tool with no way back,
and remembering a transform tool makes the strip ping-pong between Move and
Rotate instead of letting them out. Hence the pure decision functions are
pinned here, plus the wiring that keeps the strip, the shared constants and
the module's lack of operators from drifting apart.

One wiring test is a REGRESSION GUARD, not a style preference: the buttons
must keep dispatching the stock `wm.tool_set_by_id`, because Blender decides
a button is a toolbar tool button by matching its operator against
`WM_OT_tool_set_by_id` by pointer (`but_is_tool`, `interface_query.cc`). A
custom operator in the strip draws as three plain buttons — the visual
regression this design replaced.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.workflow import constants
from mixar.modules.workflow.ui.headers import view3d_header_filter as HEADER
from mixar.modules.workflow.ui.operators import zen_tool_toggle as TOGGLE

TOGGLE_PATH = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "ui" / "operators" /
    "zen_tool_toggle.py"
)
TOGGLE_SRC = TOGGLE_PATH.read_text(encoding="utf-8")
HEADER_SRC = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "ui" / "headers" /
    "view3d_header_filter.py"
).read_text(encoding="utf-8")
BOOTSTRAP_SRC = (
    SCRIPTS / "mixar" / "bootstrap" / "workflow_module.py"
).read_text(encoding="utf-8")

MOVE, ROTATE, SCALE = constants.ZEN_TRANSFORM_TOOL_IDS
TRANSFORMS = constants.ZEN_TRANSFORM_TOOL_IDS
FALLBACK = "builtin.select"
SELECT_TOOL = "builtin.select_box"


def _remember(monkeypatch, previous):
    """Force the module's one memory slot to a known value."""
    monkeypatch.setattr(TOGGLE, "_previous_tool_idname", previous)


def _strip_body():
    """The source of `_patched_tools_active_draw` alone."""
    body = HEADER_SRC.split("def _patched_tools_active_draw", 1)[1]
    return body.split("def install_view3d_header_filter", 1)[0]


# ---------------------------------------------------------------------------
# The decision itself
# ---------------------------------------------------------------------------


def test_clicking_an_inactive_transform_tool_activates_it(monkeypatch):
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.toggle_target(MOVE, SELECT_TOOL, FALLBACK) == MOVE


def test_clicking_the_active_transform_tool_restores_the_previous_tool(monkeypatch):
    """The whole point of the toggle: off means "back to my select tool"."""
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.toggle_target(MOVE, MOVE, FALLBACK) == SELECT_TOOL


def test_clicking_the_active_transform_tool_without_memory_uses_the_fallback(monkeypatch):
    _remember(monkeypatch, None)
    assert TOGGLE.toggle_target(MOVE, MOVE, FALLBACK) == FALLBACK


def test_a_remembered_transform_tool_is_ignored(monkeypatch):
    """Defence in depth for a caller that remembers the wrong thing: toggling
    off must never hand the user back another transform tool."""
    for remembered in TRANSFORMS:
        _remember(monkeypatch, remembered)
        assert TOGGLE.toggle_target(MOVE, MOVE, FALLBACK) == FALLBACK


def test_clicking_the_active_tool_never_returns_a_transform_tool(monkeypatch):
    """Exhaustive over the trio, with and without memory, because "no way out
    of the strip" is the failure this feature exists to prevent."""
    for clicked in TRANSFORMS:
        for remembered in (None, *TRANSFORMS):
            _remember(monkeypatch, remembered)
            target = TOGGLE.toggle_target(clicked, clicked, FALLBACK)
            assert target not in TRANSFORMS


def test_switching_directly_between_transform_tools_keeps_the_memory(monkeypatch):
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.toggle_target(SCALE, ROTATE, FALLBACK) == SCALE


def test_a_remembered_tool_that_no_longer_resolves_falls_back(monkeypatch):
    """A tool remembered from another mode may not exist here; the click still
    has to leave the user somewhere valid rather than cancel silently."""
    _remember(monkeypatch, "brush.gone")
    assert TOGGLE.toggle_target(
        MOVE, MOVE, FALLBACK, lambda idname: idname != "brush.gone"
    ) == FALLBACK


def test_a_remembered_tool_that_still_resolves_is_used(monkeypatch):
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.toggle_target(
        MOVE, MOVE, FALLBACK, lambda idname: idname == SELECT_TOOL
    ) == SELECT_TOOL


def test_availability_is_not_consulted_when_activating_a_different_tool(monkeypatch):
    """Clicking a tool that is not active needs no memory and no registry
    lookup; an availability predicate that rejects everything must not stop
    it."""
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.toggle_target(
        MOVE, SELECT_TOOL, FALLBACK, lambda idname: False
    ) == MOVE


# ---------------------------------------------------------------------------
# The memory feeding the decision
# ---------------------------------------------------------------------------


def test_only_non_transform_tools_are_remembered(monkeypatch):
    _remember(monkeypatch, None)
    TOGGLE.note_active_tool(SELECT_TOOL)
    assert TOGGLE.previous_tool_idname() == SELECT_TOOL


def test_activating_a_transform_tool_over_another_keeps_the_old_memory(monkeypatch):
    """Move -> Rotate -> Rotate must return to the select tool, not to Move,
    so a transform tool must never overwrite the remembered slot."""
    _remember(monkeypatch, SELECT_TOOL)
    for active in TRANSFORMS:
        TOGGLE.note_active_tool(active)
        assert TOGGLE.previous_tool_idname() == SELECT_TOOL


def test_move_then_rotate_then_rotate_returns_to_the_select_tool(monkeypatch):
    """The end-to-end sequence the memory exists for, without a live Blender:
    the draw notes every active tool, so the memory is already correct by the
    time the click lands."""
    _remember(monkeypatch, SELECT_TOOL)
    TOGGLE.note_active_tool(MOVE)
    assert TOGGLE.toggle_target(ROTATE, ROTATE, FALLBACK) == SELECT_TOOL


def test_nothing_active_remembers_nothing(monkeypatch):
    _remember(monkeypatch, SELECT_TOOL)
    for nothing in (None, ""):
        TOGGLE.note_active_tool(nothing)
        assert TOGGLE.previous_tool_idname() == SELECT_TOOL


def test_previous_tool_idname_reads_the_remembered_slot(monkeypatch):
    _remember(monkeypatch, SELECT_TOOL)
    assert TOGGLE.previous_tool_idname() == SELECT_TOOL


# ---------------------------------------------------------------------------
# Wiring: the strip keeps the stock tool operator
# ---------------------------------------------------------------------------


def test_the_strip_dispatches_the_stock_tool_operator():
    """REGRESSION GUARD. `but_is_tool` matches the button's operator against
    `WM_OT_tool_set_by_id` by pointer; any other operator makes the three
    buttons draw as plain `Exec` buttons (no toolbar widget style, no toolbar
    icon size, no SVG scaling)."""
    strip = _strip_body()
    assert '"wm.tool_set_by_id"' in strip
    assert ".name = zen_tool_toggle.toggle_target(" in strip


def test_the_strip_dispatches_no_custom_operator():
    strip = _strip_body()
    assert "mixar.toggle" not in strip
    assert "mixar.zen" not in strip


def test_the_toggle_target_is_computed_per_button_not_once_for_the_strip():
    """Each button carries its own target: the active one is handed the way
    out while the other two are handed themselves."""
    strip = _strip_body()
    assert "for idname, item in items:" in strip
    loop = strip.split("for idname, item in items:", 1)[1]
    assert "toggle_target(" in loop


def test_the_strip_feeds_the_memory_before_the_workspace_bail():
    """A tool picked in Engine Mode (or from a keymap) has to be the way out
    by the time Zen Mode's strip comes up, so the note happens on every draw,
    before the `_is_basic_workspace` early return."""
    strip = _strip_body()
    assert strip.index("zen_tool_toggle.note_active_tool(") < strip.index(
        "_is_basic_workspace"
    )


def test_the_strip_passes_the_live_fallback_and_resolver_to_the_decision():
    strip = _strip_body()
    assert "fallback_idname = _fallback_tool_idname()" in strip
    assert "resolves = _tool_resolves(cls, context)" in strip


def test_both_halves_share_one_definition_of_the_transform_tools():
    assert TRANSFORMS == ("builtin.move", "builtin.rotate", "builtin.scale")
    assert HEADER.ZEN_TRANSFORM_TOOL_IDS is TRANSFORMS
    assert TOGGLE.ZEN_TRANSFORM_TOOL_IDS is TRANSFORMS
    assert "_ZEN_TOOL_IDS" not in HEADER_SRC, (
        "a second copy of the tool ids is what lets the strip and the toggle "
        "disagree about which tools are transforms"
    )


# ---------------------------------------------------------------------------
# Wiring: the strip's small context helpers
# ---------------------------------------------------------------------------


def test_active_tool_idname_is_none_without_a_helper():
    assert HEADER._active_tool_idname(None, SimpleNamespace()) is None


def test_active_tool_idname_survives_a_failing_helper():
    """A draw callback must never raise: `tool_active_from_context` reaches
    into `context.space_data` and can fail on an area mid-switch."""
    class Boom:
        @staticmethod
        def tool_active_from_context(context):
            raise RuntimeError("no space_data in this draw")

    assert HEADER._active_tool_idname(Boom, SimpleNamespace()) is None


def test_active_tool_idname_reads_the_active_tool():
    helper = SimpleNamespace(
        tool_active_from_context=lambda context: SimpleNamespace(idname=MOVE)
    )
    assert HEADER._active_tool_idname(helper, SimpleNamespace()) == MOVE


def test_the_fallback_is_read_off_the_registered_panel(monkeypatch):
    """Read live so a change to the panel's own `tool_fallback_id` is picked
    up rather than duplicated in the strip."""
    panel = SimpleNamespace(tool_fallback_id=SELECT_TOOL)
    monkeypatch.setattr(HEADER.bpy.types, "VIEW3D_PT_tools_active", panel, raising=False)
    assert HEADER._fallback_tool_idname() == SELECT_TOOL


def test_tool_resolves_predicate_follows_tool_get_by_id():
    context = SimpleNamespace()
    panel = SimpleNamespace(_tool_get_by_id=lambda ctx, idname: (idname, 0))
    assert HEADER._tool_resolves(panel, context)(MOVE) is True

    missing = SimpleNamespace(_tool_get_by_id=lambda ctx, idname: (None, -1))
    assert HEADER._tool_resolves(missing, context)("brush.gone") is False


def test_tool_resolves_predicate_survives_a_failing_lookup():
    context = SimpleNamespace()

    def boom(ctx, idname):
        raise KeyError("no tool registry in this context")

    assert HEADER._tool_resolves(SimpleNamespace(_tool_get_by_id=boom), context)("x") is False


# ---------------------------------------------------------------------------
# Wiring: nothing to register
# ---------------------------------------------------------------------------


def test_the_toggle_module_defines_no_operators():
    """The toggle is decided at draw time, so there is no operator to register
    — and none whose re-registration could free a wmOperatorType still
    referenced by a drawn button."""
    assert "MIXAR_OT_" not in TOGGLE_SRC
    assert "register_class" not in TOGGLE_SRC
    assert TOGGLE_SRC.rstrip().endswith("classes = ()")
    assert TOGGLE.classes == ()


def test_the_bootstrap_registers_only_the_mode_operators():
    assert "_all_classes = ui_mode_classes" in BOOTSTRAP_SRC
    assert "zen_tool" not in BOOTSTRAP_SRC
