# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Agent Bubble must not offer window controls it cannot honour.

Minimise, restore and expand are native operators whose bodies are compiled
only for macOS and Windows — the ``Mixar_Window*`` GHOST helpers they call
exist in ``GHOST_SystemCocoa.mm`` and ``GHOST_SystemWin32.cc`` and nowhere
else. On Linux the three ``exec`` functions in ``space_agent_bubble.cc`` are
``return OPERATOR_CANCELLED``, and because every call site sits inside the
same ``#if`` the build links cleanly with no warning.

The buttons were still drawn, enabled, and dispatching. Clicking one produced
no window change, no error, no toast and no log line, which reads as frozen
UI. Worse, the surrounding Python ran its side effects anyway: ESC recorded
the user-dismissal that mutes the autoshow, and Ctrl/Cmd+Shift+B reported
FINISHED and logged a "maximized" event for a window that never moved.

What is pinned here is the honesty of the surface, not the platform list:
where the native side is a stub, nothing is offered and nothing is recorded.
"""

import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

# pill_icons does `import bpy.utils.previews`, which the root conftest's stub
# hierarchy doesn't reach.
sys.modules.setdefault("bpy.utils.previews", MagicMock(name="bpy.utils.previews"))

from mixar.modules.testing.mock_bpy import install_bpy_mock

install_bpy_mock()

from mixar.modules.agent_bubble import constants as CONST


def _load_header_module():
    """Import the header with a REAL Header base class.

    `bpy.types.Header` is a MagicMock, and subclassing a mock produces
    another mock — `AGENT_BUBBLE_HT_header.draw` would then be an
    auto-attribute rather than the function under test. Loading a private
    copy under its own module name keeps this independent of whichever
    other test imported the shared module first.
    """
    import importlib.util

    import bpy

    path = (
        SCRIPTS / "mixar" / "modules" / "agent_bubble" / "ui" / "header.py"
    )
    spec = importlib.util.spec_from_file_location(
        "_agent_bubble_header_under_test", path
    )
    module = importlib.util.module_from_spec(spec)
    saved = bpy.types.Header
    bpy.types.Header = type("Header", (), {})
    try:
        spec.loader.exec_module(module)
    finally:
        bpy.types.Header = saved
    return module


HDR = _load_header_module()


# ---------------------------------------------------------------------------
# A layout that records what the header asked for
# ---------------------------------------------------------------------------


class FakeLayout:
    """Records operator/label calls and the rows created to hold them."""

    def __init__(self, sink=None):
        self.sink = sink if sink is not None else {"ops": [], "labels": [], "rows": []}
        self.alignment = 'EXPAND'
        self.scale_y = 1.0

    def row(self, align=False):
        child = FakeLayout(self.sink)
        self.sink["rows"].append(child)
        return child

    def operator(self, idname, **kwargs):
        self.sink["ops"].append(idname)
        return SimpleNamespace()

    def label(self, text="", **kwargs):
        self.sink["labels"].append(text)

    def separator_spacer(self):
        pass

    def separator(self, **kwargs):
        pass

    @property
    def ops(self):
        return self.sink["ops"]

    @property
    def labels(self):
        return self.sink["labels"]


def _context(*, pill: bool):
    """A bubble context. The pill window is the one with no TOOLS region."""
    regions = [SimpleNamespace(type='HEADER')]
    if not pill:
        regions.append(SimpleNamespace(type='TOOLS'))
    return SimpleNamespace(
        area=SimpleNamespace(regions=regions),
        scene=SimpleNamespace(mixie_chat_state="IDLE", mixie_chat_messages=[]),
        window_manager=SimpleNamespace(
            mixie_chat_is_logged_in=False,
            mixie_chat_history_visible=False,
        ),
    )


def _draw(monkeypatch, *, supported: bool, pill: bool = False,
          windows: bool = False):
    monkeypatch.setattr(HDR, "BUBBLE_WINDOW_CONTROLS_SUPPORTED", supported)
    monkeypatch.setattr(HDR, "_IS_WINDOWS", windows)
    monkeypatch.setattr(HDR, "_transport_down", lambda: False)
    monkeypatch.setattr(HDR, "_queue_activity", lambda: None)
    # The macOS-shaped branch draws its traffic lights as custom pill icons
    # and skips a button whose icon failed to load; previews are mocked here,
    # so hand it an id.
    monkeypatch.setattr(HDR, "get_pill_icon_id_named", lambda name: 1)
    layout = FakeLayout()
    header = SimpleNamespace(layout=layout)
    HDR.AGENT_BUBBLE_HT_header.draw(header, _context(pill=pill))
    return layout


WINDOW_CONTROL_OPS = {
    "mixar.bubble_close",
    "mixar.bubble_restore_user",
    "mixar.bubble_toggle_expand_tracked",
}


# ---------------------------------------------------------------------------
# The main bubble header
# ---------------------------------------------------------------------------


def test_macos_still_offers_the_traffic_lights(monkeypatch):
    ops = _draw(monkeypatch, supported=True).ops
    assert "mixar.bubble_close" in ops
    assert "mixar.bubble_toggle_expand_tracked" in ops


def test_windows_still_offers_the_window_controls(monkeypatch):
    ops = _draw(monkeypatch, supported=True, windows=True).ops
    assert "mixar.bubble_close" in ops
    assert "mixar.bubble_toggle_expand_tracked" in ops


def test_stubbed_platform_offers_no_window_controls(monkeypatch):
    ops = _draw(monkeypatch, supported=False).ops
    assert not WINDOW_CONTROL_OPS.intersection(ops), (
        "the bubble drew a window control whose operator is a compiled-out "
        f"stub on this platform: {sorted(WINDOW_CONTROL_OPS.intersection(ops))}"
    )


def test_the_drag_handle_survives_the_gate(monkeypatch):
    """Dragging works on every platform and is not part of the gate."""
    assert "▬▬▬▬" in _draw(monkeypatch, supported=False).labels


def test_no_empty_row_is_left_behind(monkeypatch):
    """An empty aligned row still takes header space and would shift the
    centred drag handle off centre, so the row itself must be skipped."""
    gated = _draw(monkeypatch, supported=False)
    supported = _draw(monkeypatch, supported=True)
    # one row for the traffic lights, drawn only where they work
    assert len(gated.sink["rows"]) == len(supported.sink["rows"]) - 1


def test_right_side_controls_are_untouched(monkeypatch):
    """Only the traffic row is platform-gated."""
    ctx = _context(pill=False)
    ctx.scene.mixie_chat_messages = [object()]
    monkeypatch.setattr(HDR, "BUBBLE_WINDOW_CONTROLS_SUPPORTED", False)
    monkeypatch.setattr(HDR, "_transport_down", lambda: False)
    monkeypatch.setattr(HDR, "_queue_activity", lambda: None)
    layout = FakeLayout()
    HDR.AGENT_BUBBLE_HT_header.draw(SimpleNamespace(layout=layout), ctx)
    assert "mixie_chat.new_session" in layout.ops


# ---------------------------------------------------------------------------
# The minimised pill
# ---------------------------------------------------------------------------


def test_pill_is_clickable_where_restore_works(monkeypatch):
    ops = _draw(monkeypatch, supported=True, pill=True).ops
    assert ops == ["mixar.bubble_restore_user"]


def test_pill_is_a_plain_label_where_restore_is_stubbed(monkeypatch):
    """The status must still read — only the dead click is removed."""
    layout = _draw(monkeypatch, supported=False, pill=True)
    assert layout.ops == []
    assert layout.labels, "the pill drew nothing at all"


# ---------------------------------------------------------------------------
# The operators behind the buttons (ESC and Ctrl/Cmd+Shift+B reach these
# without going through the header at all)
# ---------------------------------------------------------------------------


def _source(name):
    path = (
        SCRIPTS / "mixar" / "modules" / "agent_bubble" / "ui" / "operators" / name
    )
    return path.read_text()


def test_every_window_state_operator_polls_the_platform():
    """A hidden button is not enough: ESC binds mixar.bubble_close in the
    global Window keymap and Ctrl/Cmd+Shift+B binds
    mixar.bubble_toggle_minimise, neither of which the header draws."""
    import ast

    tree = ast.parse(_source("bubble_close_op.py"))
    gated = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for fn in node.body:
            if not isinstance(fn, ast.FunctionDef) or fn.name != "poll":
                continue
            names = {
                n.id for n in ast.walk(fn) if isinstance(n, ast.Name)
            }
            if "BUBBLE_WINDOW_CONTROLS_SUPPORTED" in names:
                gated.add(node.name)

    assert gated == {
        "MIXAR_OT_bubble_close",
        "MIXAR_OT_bubble_restore_user",
        "MIXAR_OT_bubble_toggle_minimise",
        "MIXAR_OT_bubble_toggle_expand_tracked",
    }


def test_the_platform_gate_is_an_allowlist():
    """`!= "win32"` is what put Linux in the macOS branch to begin with. A
    platform opts IN by having its window helpers written."""
    src = (
        SCRIPTS / "mixar" / "modules" / "agent_bubble" / "constants.py"
    ).read_text()
    assert 'sys.platform in {"darwin", "win32"}' in src
    assert CONST.BUBBLE_WINDOW_CONTROLS_SUPPORTED == (
        sys.platform in {"darwin", "win32"}
    )
