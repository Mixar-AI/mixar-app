# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The agent viewport lock yields to a menu / popover / dialog already open.

The lock's window modal is started when the agent turns BUSY. Blender inserts
a later modal handler AHEAD of the pop-up's UI handler, so it consumed the
pop-up's clicks over the viewport rectangle (where AI Provider Settings
floats) and its hotkey letters (an API key containing "s"): the dialog could
not be cancelled once the halo started. While native
``Window.mixar_popup_block_open()`` reports a pop-up block the lock passes
EVERY event through; the pop-up handler blocks what it does not use.
"""

import ast
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

import pytest

from mixar.modules.agent_viewport_lock.constants import (
    BLOCK_KEY_TYPES,
    BLOCK_MOUSE_TYPES,
)
from mixar.modules.agent_viewport_lock.ui.operators import viewport_block_op as VBO

POPUP_QUERY = ROOT / "src/source/blender/editors/interface/mixar/popup_query.cc"
RNA_POPUP = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar_popup.cc"
RNA_WM_MIXAR = ROOT / "src/source/blender/makesrna/intern/rna_wm_mixar.cc"
INTERFACE_CMAKE = ROOT / "src/source/blender/editors/interface/CMakeLists.txt"


@pytest.fixture(autouse=True)
def _real_operator(monkeypatch):
    # Root conftest mocks bpy.types.Operator: compile the real class body with
    # a plain base so the modal logic itself runs.
    tree = ast.parse(Path(VBO.__file__).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "MIXAR_OT_agent_viewport_block")
    cls.bases = [ast.Name(id="object", ctx=ast.Load())]
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(VBO.__dict__)
    exec(compile(module, VBO.__file__, "exec"), namespace)
    monkeypatch.setattr(VBO, cls.name, namespace[cls.name])
    namespace["is_agent_executing"] = lambda: VBO.is_agent_executing()
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: True)


def _context(popup=None):
    """A window whose only VIEW_3D canvas covers (0, 0)-(1200, 800).

    ``popup`` None → a binary without the native query (attribute absent).
    """
    region = SimpleNamespace(type="WINDOW", x=0, y=0, width=1200, height=800)
    area = SimpleNamespace(type="VIEW_3D", regions=[region],
                           mixar_moodboard_contains=lambda x, y: False,
                           mixar_header_contains=lambda x, y: False)
    window = SimpleNamespace(screen=SimpleNamespace(areas=[area]), modal_operators={})
    if popup is not None:
        window.mixar_popup_block_open = popup
    return SimpleNamespace(window=window)


def _modal(context, type, value="PRESS"):
    event = SimpleNamespace(type=type, value=value, mouse_x=600, mouse_y=400)
    return VBO.MIXAR_OT_agent_viewport_block().modal(context, event)


BLOCKED = sorted(BLOCK_MOUSE_TYPES | BLOCK_KEY_TYPES)


@pytest.mark.parametrize("event_type", BLOCKED)
@pytest.mark.parametrize("value", ["PRESS", "RELEASE"])
def test_every_blocked_event_passes_while_a_popup_is_open(event_type, value):
    assert _modal(_context(lambda: True), event_type, value) == {"PASS_THROUGH"}


@pytest.mark.parametrize("event_type", BLOCKED)
def test_viewport_stays_locked_without_a_popup(event_type):
    assert _modal(_context(lambda: False), event_type) == {"RUNNING_MODAL"}


def test_typing_an_s_reaches_the_dialog_field():
    # The reported case: an API key containing "s" under the halo.
    assert "S" in BLOCK_KEY_TYPES
    assert _modal(_context(lambda: True), "S") == {"PASS_THROUGH"}


def test_cancel_click_over_the_viewport_reaches_the_dialog():
    assert _modal(_context(lambda: True), "LEFTMOUSE") == {"PASS_THROUGH"}
    assert _modal(_context(lambda: True), "LEFTMOUSE", "RELEASE") == {"PASS_THROUGH"}


def test_binary_without_the_native_query_keeps_blocking():
    assert _modal(_context(None), "LEFTMOUSE") == {"RUNNING_MODAL"}
    assert _modal(_context(None), "S") == {"RUNNING_MODAL"}


def test_query_failure_keeps_blocking():
    def boom():
        raise RuntimeError("window going away")

    assert _modal(_context(boom), "LEFTMOUSE") == {"RUNNING_MODAL"}


def test_only_a_real_true_yields():
    # Mock windows elsewhere in the suite answer every attribute with a
    # truthy MagicMock; only RNA's bool True may unlock the viewport.
    assert _modal(_context(lambda: object()), "LEFTMOUSE") == {"RUNNING_MODAL"}


def test_lock_still_stops_when_the_agent_is_done(monkeypatch):
    monkeypatch.setattr(VBO, "is_agent_executing", lambda: False)
    op = VBO.MIXAR_OT_agent_viewport_block()
    finished = []
    op._finish = lambda context: finished.append(True)
    event = SimpleNamespace(type="LEFTMOUSE", value="PRESS", mouse_x=600, mouse_y=400)
    assert op.modal(_context(lambda: True), event) == {"FINISHED"}
    assert finished == [True]


# --- the native side ------------------------------------------------------

def test_native_query_counts_popup_blocks_not_tooltips():
    src = POPUP_QUERY.read_text()
    assert "bool Mixar_window_popup_block_open(wmWindow *win)" in src
    # Pop-ups live in the window's temporary regions; a block only carries a
    # PopupBlockHandle while a pop-up owns it (tooltips have no block).
    assert "screen->regionbase" in src
    assert "block.handle != nullptr" in src
    assert "namespace blender {" in src
    assert "mixar/popup_query.cc" in INTERFACE_CMAKE.read_text()


def test_window_rna_function_is_registered():
    rna = RNA_POPUP.read_text()
    assert '"mixar_popup_block_open", "rna_Window_mixar_popup_block_open"' in rna
    assert "RNA_def_function_return" in rna
    host = RNA_WM_MIXAR.read_text()
    # Included above the namespace wrap, like rna_wm_ui_control.cc.
    assert host.index('#include "rna_wm_mixar_popup.cc"') < host.index("namespace blender {")
    assert "RNA_def_mixar_popup_query(brna, srna);" in host
    assert len(host.splitlines()) <= 500
