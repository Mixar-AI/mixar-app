# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Agent Bubble must not offer window controls it cannot honour.

Minimise, restore and expand are native operators whose bodies are compiled
only for macOS and Windows — the ``Mixar_Window*`` GHOST helpers they call
exist in ``GHOST_SystemCocoa.mm`` and ``GHOST_SystemWin32.cc`` and nowhere
else. On Linux the three ``exec`` functions in ``space_agent_bubble.cc`` are
``return OPERATOR_CANCELLED``; every call site sits inside the same ``#if``,
and the APIs the cross-platform Cinema gate consumes get Linux definitions,
so the build compiles and links cleanly with no warning.

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
    return path.read_text(encoding="utf-8")


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
    ).read_text(encoding="utf-8")
    assert 'sys.platform in {"darwin", "win32"}' in src
    assert CONST.BUBBLE_WINDOW_CONTROLS_SUPPORTED == (
        sys.platform in {"darwin", "win32"}
    )


# ---------------------------------------------------------------------------
# The C++ side of the same invariant
# ---------------------------------------------------------------------------

BUBBLE_CC = (
    ROOT
    / "src"
    / "source"
    / "blender"
    / "editors"
    / "space_agent_bubble"
    / "space_agent_bubble.cc"
)

CINEMA_SEAT_GLOBALS = (
    "g_pill_cinema_seat_valid",
    "g_pill_cinema_host",
    "g_pill_cinema_bottom_px",
)

# ``ED_space_api.hh`` declares both unconditionally, and
# ``view3d_director_cinema_gate.cc`` — a file with no platform conditionals
# at all — calls both, so neither may be Apple/Windows-only.
CINEMA_SEAT_FUNCTION_SIGNATURES = (
    "void ED_agent_bubble_set_cinema_seat(",
    "int ED_agent_bubble_pill_band_px(",
)


def _directive(line):
    """The preprocessor keyword of `line`, or "".

    `#  ifdef __APPLE__` is legal C, so the padding after the `#` is
    normalised before matching.
    """
    stripped = line.strip()
    if not stripped.startswith("#"):
        return ""
    return stripped[1:].strip()


def _linux_preprocessor_pass(source):
    """Split `space_agent_bubble.cc` into what a Linux build keeps and what
    the platform guards drop.

    Every conditional in the file is stated as one of
    ``#if defined(__APPLE__) || defined(_WIN32)``, ``#ifdef __APPLE__`` or
    ``#ifdef _WIN32`` — all false on Linux — so the plain
    ``#if``/``#else``/``#endif`` nesting is an exact answer here. Any other
    conditional form aborts rather than silently guessing.
    """
    live = []
    guarded = []
    active = True
    stack = []
    for line in source.splitlines():
        directive = _directive(line)
        if directive.startswith(("if ", "ifdef ", "ifndef ")):
            assert directive.startswith(
                (
                    "if defined(__APPLE__) || defined(_WIN32)",
                    "ifdef __APPLE__",
                    "ifdef _WIN32",
                )
            ), f"unexpected platform conditional: {directive!r}"
            stack.append((active, False))
            active = False
        elif directive.startswith("else"):
            parent, _taken = stack[-1]
            active = parent
            stack[-1] = (parent, True)
        elif directive.startswith("endif"):
            active, _taken = stack.pop()
        elif directive.startswith("elif"):
            raise AssertionError(f"unexpected conditional: {directive!r}")
        (live if active else guarded).append(line)
    assert not stack, "unbalanced preprocessor conditionals"
    return live, guarded


def test_the_cinema_seat_functions_have_a_linux_definition():
    """Regression (Linux link error): the Cinema seat functions were defined
    only inside the Apple/Windows guard. The compile errors hid it — a link
    only runs once every translation unit compiles — but the gate calls them
    from a file with no platform conditionals, so Linux failed on undefined
    references as soon as the two "was not declared in this scope" errors
    were fixed."""
    live, guarded = _linux_preprocessor_pass(BUBBLE_CC.read_text(encoding="utf-8"))
    # Without a platform guard in the file this test would be vacuous.
    assert guarded, "no platform-guarded lines to contrast against"
    for signature in CINEMA_SEAT_FUNCTION_SIGNATURES:
        assert any(signature in line for line in live), (
            f"{signature!r} has no definition that survives a Linux build; "
            "the cross-platform Cinema gate calls it, so Linux fails to link"
        )


def test_no_cinema_seat_global_is_used_without_a_linux_declaration():
    """Regression (Linux compile error, which only ever showed on Linux): the
    Cinema seat globals were declared inside the Apple/Windows guard while
    ``ED_agent_bubble_windows_closed()`` reset two of them unconditionally —
    "'g_pill_cinema_seat_valid' was not declared in this scope", then the same
    for 'g_pill_cinema_host'."""
    live, _guarded = _linux_preprocessor_pass(BUBBLE_CC.read_text(encoding="utf-8"))
    for name in CINEMA_SEAT_GLOBALS:
        referenced = [line for line in live if name in line]
        if not referenced:
            # Declared and used only under the guard: nothing survives.
            continue
        assert any(line.lstrip().startswith("static ") for line in referenced), (
            f"{name} is referenced in code that survives a Linux build but is "
            f"only declared for Apple/Windows: {referenced[0].strip()!r}"
        )


def test_the_per_pixel_alpha_flag_is_reset_with_the_window_it_describes():
    """`g_pill_per_pixel_alpha` is declared inside the same Apple/Windows guard
    as the Cinema seat globals, and its consumer
    (`agent_bubble_pill_bed_is_transparent()`) runs on every pill draw. It is
    the pill's record that this window handed its silhouette to DWM, so it may
    not outlive that window: left set across a close cycle, the next session's
    bed writes alpha 0 before `Mixar_WindowSetPerPixelAlpha` has decided
    anything. Neither close path cleared it.
    """
    source = BUBBLE_CC.read_text(encoding="utf-8")
    live, guarded = _linux_preprocessor_pass(source)
    reset = "g_pill_per_pixel_alpha = false;"
    resets = [
        line
        for line in live + guarded
        if reset in line and not line.lstrip().startswith("static ")
    ]
    assert resets, f"nothing in the file resets {reset!r}"
    assert all(line in guarded for line in resets), (
        f"{reset!r} is reset in code a Linux build keeps, but the flag is "
        "declared only for Apple/Windows — Linux fails with 'was not declared "
        "in this scope'"
    )
    closed = source[source.index("void ED_agent_bubble_windows_closed()") :]
    closed = closed[: closed.index("\n}\n")]
    assert reset in closed, (
        "the reset belongs in ED_agent_bubble_windows_closed(), the choke point "
        "every close path funnels through"
    )
