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
the eager registration from drifting apart.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.workflow import constants
from mixar.modules.workflow.ui.headers import view3d_header_filter as HEADER
from mixar.modules.workflow.ui.operators import zen_tool_ops as OPS

OPS_PATH = (
    SCRIPTS / "mixar" / "modules" / "workflow" / "ui" / "operators" / "zen_tool_ops.py"
)
OPS_SRC = OPS_PATH.read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------
# The decision itself
# ---------------------------------------------------------------------------


def test_clicking_an_inactive_transform_tool_activates_it():
    assert OPS._tool_to_activate(MOVE, "builtin.select_box", None, FALLBACK) == MOVE


def test_clicking_the_active_transform_tool_restores_the_previous_tool():
    """The whole point of the toggle: off means "back to my select tool"."""
    assert OPS._tool_to_activate(MOVE, MOVE, "builtin.select_box", FALLBACK) == (
        "builtin.select_box"
    )


def test_clicking_the_active_transform_tool_without_memory_uses_the_fallback():
    assert OPS._tool_to_activate(MOVE, MOVE, None, FALLBACK) == FALLBACK


def test_a_remembered_transform_tool_is_ignored():
    """Defence in depth for a caller that remembers the wrong thing: toggling
    off must never hand the user back another transform tool."""
    for remembered in TRANSFORMS:
        assert OPS._tool_to_activate(MOVE, MOVE, remembered, FALLBACK) == FALLBACK


def test_clicking_the_active_tool_never_returns_a_transform_tool():
    """Exhaustive over the trio, with and without memory, because "no way out
    of the strip" is the failure this feature exists to prevent."""
    for clicked in TRANSFORMS:
        for remembered in (None, *TRANSFORMS):
            target = OPS._tool_to_activate(clicked, clicked, remembered, FALLBACK)
            assert target not in TRANSFORMS


def test_only_non_transform_tools_are_remembered():
    assert OPS._tool_to_remember("builtin.select_box") == "builtin.select_box"


def test_activating_a_transform_tool_over_another_keeps_the_old_memory():
    """Move -> Rotate -> Rotate must return to the select tool, not to Move,
    so a transform tool must never overwrite the remembered slot."""
    for active in TRANSFORMS:
        assert OPS._tool_to_remember(active) is None


def test_nothing_active_remembers_nothing():
    assert OPS._tool_to_remember(None) is None


# ---------------------------------------------------------------------------
# The operator around it
# ---------------------------------------------------------------------------


def _click(tool_idname):
    """A stand-in for the operator instance a toolbar button invokes."""
    return SimpleNamespace(tool_idname=tool_idname, report=lambda kind, message: None)


def _arm(monkeypatch, active, previous=None):
    monkeypatch.setattr(OPS, "_previous_tool_idname", previous)
    monkeypatch.setattr(OPS, "_active_tool_idname", lambda context: active)


@pytest.fixture
def activated(monkeypatch):
    """Collect every tool activation the operator would perform."""
    calls = []

    def fake_set_active(idname):
        calls.append(idname)
        return True

    monkeypatch.setattr(OPS, "_set_active_tool", fake_set_active)
    monkeypatch.setattr(OPS, "_fallback_tool_idname", lambda: FALLBACK)
    return calls


def test_activating_remembers_the_tool_it_displaced(monkeypatch, activated):
    _arm(monkeypatch, "builtin.select_box")
    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(_click(MOVE), None) == {"FINISHED"}
    assert activated == [MOVE]
    assert OPS._previous_tool_idname == "builtin.select_box"


def test_toggling_off_restores_the_remembered_tool(monkeypatch, activated):
    _arm(monkeypatch, MOVE, previous="builtin.select_box")
    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(_click(MOVE), None) == {"FINISHED"}
    assert activated == ["builtin.select_box"]
    assert OPS._previous_tool_idname == "builtin.select_box", (
        "restoring must not consume the memory — the next click has to find it"
    )


def test_toggling_off_without_memory_falls_back_to_the_panel_tool(monkeypatch, activated):
    _arm(monkeypatch, MOVE)
    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(_click(MOVE), None) == {"FINISHED"}
    assert activated == [FALLBACK]


def test_switching_directly_between_transform_tools_keeps_the_memory(monkeypatch, activated):
    _arm(monkeypatch, ROTATE, previous="builtin.select_box")
    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(_click(SCALE), None) == {"FINISHED"}
    assert activated == [SCALE]
    assert OPS._previous_tool_idname == "builtin.select_box"


def test_a_refused_tool_falls_back_rather_than_doing_nothing(monkeypatch):
    """A tool remembered from another mode may not exist here; the click still
    has to leave the user somewhere valid."""
    attempted = []
    monkeypatch.setattr(
        OPS, "_set_active_tool",
        lambda idname: attempted.append(idname) or idname != "brush.gone",
    )
    monkeypatch.setattr(OPS, "_fallback_tool_idname", lambda: FALLBACK)
    _arm(monkeypatch, MOVE, previous="brush.gone")

    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(_click(MOVE), None) == {"FINISHED"}
    assert attempted == ["brush.gone", FALLBACK]


def test_a_click_that_cannot_activate_anything_reports_and_cancels(monkeypatch):
    reports = []
    monkeypatch.setattr(OPS, "_set_active_tool", lambda idname: False)
    monkeypatch.setattr(OPS, "_fallback_tool_idname", lambda: FALLBACK)
    _arm(monkeypatch, MOVE)
    op = _click(MOVE)
    op.report = lambda kind, message: reports.append((kind, message))

    assert OPS.MIXAR_OT_toggle_zen_transform_tool.execute(op, None) == {"CANCELLED"}
    assert reports and reports[-1][0] == {"WARNING"}


def test_the_fallback_is_read_off_the_registered_panel(monkeypatch):
    panel = SimpleNamespace(tool_fallback_id="builtin.select_box")
    monkeypatch.setattr(OPS.bpy.types, "VIEW3D_PT_tools_active", panel, raising=False)
    assert OPS._fallback_tool_idname() == "builtin.select_box"


# ---------------------------------------------------------------------------
# Wiring
# ---------------------------------------------------------------------------


def test_the_strip_dispatches_the_toggle_operator():
    assert '"mixar.toggle_zen_transform_tool"' in HEADER_SRC
    assert ".tool_idname = idname" in HEADER_SRC


def test_the_strip_no_longer_dispatches_the_stock_tool_operator():
    """`wm.tool_set_by_id` is persistent, so a strip built on it cannot toggle.
    The toggle operator still calls it internally — only the strip must not."""
    strip = HEADER_SRC.split("def _patched_tools_active_draw", 1)[1]
    strip = strip.split("def install_view3d_header_filter", 1)[0]
    assert '"wm.tool_set_by_id"' not in strip
    assert "wm.tool_set_by_id" in OPS_SRC


def test_both_halves_share_one_definition_of_the_transform_tools():
    assert TRANSFORMS == ("builtin.move", "builtin.rotate", "builtin.scale")
    assert HEADER.ZEN_TRANSFORM_TOOL_IDS is TRANSFORMS
    assert "_ZEN_TOOL_IDS" not in HEADER_SRC, (
        "a second copy of the tool ids is what lets the strip and the toggle "
        "disagree about which tools are transforms"
    )


def test_the_toggle_operator_is_registered_eagerly():
    """The toolbar filter is installed during this bootstrap, ahead of the
    deferred UI discovery pass, so the first Zen paint must not reference an
    operator that is not registered yet."""
    assert "MIXAR_OT_toggle_zen_transform_tool" in OPS_SRC.split("classes = (", 1)[1]
    assert "ui_mode_classes + zen_tool_classes" in BOOTSTRAP_SRC
    assert "zen_tool_ops import classes as zen_tool_classes" in BOOTSTRAP_SRC
