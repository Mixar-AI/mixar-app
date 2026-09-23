# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Zen scene toolbar stays above the agent halo, the lock and the sketch hint.

In Zen the View3D HEADER overlaps the top of the WINDOW region and paints an
opaque bed after it. Overlays anchored to the region top were therefore either
washed over the toolbar (the halo's top band), blocking it (the input lock's
WINDOW-rect hit test), or painted underneath it (the sketch hint pill).
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

from mixar.modules.agent_viewport_lock.ui.operators import viewport_block_op as VBO
from mixar.modules.common.utils.ui_utils import top_header_overlap_px
from mixar.modules.scribble_mark import constants as C
from mixar.modules.scribble_mark.core import overlay

# Area at window (100, 50), 800x600. With overlap the WINDOW region spans the
# whole area and the 54 px header sits over its top edge.
WIN = SimpleNamespace(type="WINDOW", x=100, y=50, width=800, height=600)


def _region(kind, y, height, width=800, x=100):
    return SimpleNamespace(type=kind, x=x, y=y, width=width, height=height)


def _area(*regions, controls=()):
    """*controls* are window rects that native header hit testing claims."""
    return SimpleNamespace(
        type="VIEW_3D", regions=[WIN, *regions],
        mixar_moodboard_contains=lambda mx, my: False,
        mixar_header_contains=lambda mx, my: any(
            x0 <= mx <= x1 and y0 <= my <= y1 for x0, y0, x1, y1 in controls),
    )


TOP_HEADER = _region("HEADER", y=596, height=54)


@pytest.mark.parametrize("regions, expected", [
    ((TOP_HEADER,), 54),
    ((TOP_HEADER, _region("TOOL_HEADER", y=570, height=26)), 80),
    # Stock layout: the header sits above the canvas, not over it.
    ((_region("HEADER", y=650, height=54),), 0),
    # Hidden regions collapse to 1x1.
    ((_region("HEADER", y=649, height=1, width=1),), 0),
    # Bottom-aligned header does not push the top overlays down.
    ((_region("HEADER", y=50, height=54),), 0),
    ((), 0),
])
def test_top_header_overlap(regions, expected):
    assert top_header_overlap_px(_area(*regions), WIN) == expected


@pytest.fixture
def block_op(monkeypatch):
    # Root conftest mocks bpy.types.Operator; compile the real class body.
    tree = ast.parse(Path(VBO.__file__).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef)
               and n.name == "MIXAR_OT_agent_viewport_block")
    cls.bases = [ast.Name(id="object", ctx=ast.Load())]
    module = ast.fix_missing_locations(ast.Module(body=[cls], type_ignores=[]))
    namespace = dict(VBO.__dict__)
    exec(compile(module, VBO.__file__, "exec"), namespace)
    return namespace[cls.name]


def _context(area):
    return SimpleNamespace(window=SimpleNamespace(screen=SimpleNamespace(areas=[area])))


# One toolbar control at window x 280..340 on the header strip.
CONTROL = (280, 606, 340, 640)


@pytest.mark.parametrize("mouse_x, mouse_y, blocked", [
    (300, 620, False),  # on a Zen toolbar control
    (600, 620, True),   # empty toolbar bed: Blender routes it to the canvas
    (300, 400, True),   # the canvas below the toolbar
])
def test_lock_passes_toolbar_controls_only(block_op, mouse_x, mouse_y, blocked):
    event = SimpleNamespace(mouse_x=mouse_x, mouse_y=mouse_y)
    area = _area(TOP_HEADER, controls=(CONTROL,))
    region = block_op._view3d_region_under_pointer(_context(area), event)
    assert (region is WIN) is blocked


def test_header_hit_test_is_native_and_registered():
    intern = ROOT / "src/source/blender/makesrna/intern"
    header = (intern / "rna_screen_mixar_header.hh").read_text()
    assert "ED_region_contains_xy(&region, xy)" in header
    assert "RGN_TYPE_HEADER, RGN_TYPE_TOOL_HEADER" in header
    assert "rna_def_area_mixar_header(srna);" in (intern / "rna_screen.cc").read_text()
    assert "rna_screen_mixar_header.hh" in (intern / "CMakeLists.txt").read_text()


def test_halo_frames_the_canvas_below_the_header():
    source = (ROOT / "src/scripts/mixar/modules/agent_viewport_lock/core/"
              "halo_renderer.py").read_text()
    assert "region.height - top_header_overlap_px(area, region)" in source


def test_sketch_hint_is_anchored_below_the_header(monkeypatch):
    drawn = {}
    monkeypatch.setattr(overlay, "_hint_text", lambda scene: C.MARK_HINT_IDLE)
    monkeypatch.setattr(overlay.blf, "dimensions", lambda *a: (200.0, 10.0))

    def _batch(shader, kind, attrs, **kw):
        drawn["pos"] = attrs["pos"]
        return SimpleNamespace(draw=lambda s: None)

    monkeypatch.setattr(overlay, "batch_for_shader", _batch)
    overlay._draw_hint(_area(TOP_HEADER), WIN, None, 1.0)
    top = max(y for _, y in drawn["pos"])
    assert top == WIN.height - 54 - C.MARK_HINT_TOP_GAP_PX


def test_every_hint_names_the_talk_key():
    assert C.MARK_HINT_VOICE == f"Hold {C.MARK_HINT_TALK_KEY}: talk"
    assert C.MARK_HINT_TALK_KEY == ("Option" if sys.platform == "darwin" else "Alt")
    for text in (C.MARK_HINT_IDLE, C.MARK_HINT_MARKED, C.MARK_HINT_SKETCH):
        assert C.MARK_HINT_VOICE in text


@pytest.mark.parametrize("owned, expected", [
    (True, "Listening · release {key}: finish · Esc: cancel"),
    (False, "Listening"),  # started from the Voice control, not the key
])
def test_talk_key_gives_way_to_voice_status(monkeypatch, owned, expected):
    from mixar.modules.space_mixie_chat import constants as chat_constants
    from mixar.modules.space_mixie_chat.core import voice
    monkeypatch.setattr(chat_constants, "VOICE_INPUT_SUPPORTED", True)
    monkeypatch.setattr(voice, "push_to_talk_owned", lambda: owned)
    wm = SimpleNamespace(mixie_chat_voice_status="Listening")
    monkeypatch.setattr(overlay, "bpy",
                        SimpleNamespace(context=SimpleNamespace(window_manager=wm)))
    text = overlay._hint_voice(C.MARK_HINT_IDLE)
    assert expected.format(key=C.MARK_HINT_TALK_KEY) in text
    assert C.MARK_HINT_VOICE not in text

    monkeypatch.setattr(chat_constants, "VOICE_INPUT_SUPPORTED", False)
    assert "talk" not in overlay._hint_voice(C.MARK_HINT_IDLE)
