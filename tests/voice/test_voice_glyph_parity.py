# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One mic, four surfaces — and nothing may quietly make it two.

The chat composer, the Agent Bubble and the moodboard node tile paint the mic
with the C++ `ED_mixar_voice_draw_button`; the N-panel cannot (a sidebar is
`UILayout` all the way down) and rasterizes the same shapes into a preview icon
instead. That leaves the glyph's proportions, palette and animation written
down TWICE, in two languages, which is exactly the kind of duplication that
rots silently: a mic that is slightly wrong in the one place the reviewer is
not looking raises no error and fails no build.

So these tests read the C++ source and assert the Python numbers against it.
What is pinned:

- every geometry ratio and every colour, by value;
- that no surface has fallen back to a stock `ICON_*` for the mic;
- that the rasterizer actually produces the glyph (a frame of empty pixels
  would satisfy a pure constants test);
- that the halo, which blooms wider than its own button, fits the icon cell.
"""

import ast
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "src" / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from mixar.modules.testing.mock_bpy import install_bpy_mock  # noqa: E402

install_bpy_mock()

from mixar.modules.voice.core import glyph_raster as raster  # noqa: E402

CPP = ROOT / "src" / "source" / "blender" / "editors"
PAINTER = (CPP / "mixar_audio" / "mixar_audio_glyph.cc").read_text()
NODE_TILE = (CPP / "space_mixie" / "mixie_draw_moodboard_node_tile_controls.cc").read_text()
CHAT = (CPP / "space_mixie_chat" / "mixie_chat_voice.cc").read_text()
DRAWER = (SCRIPTS / "mixar" / "modules" / "voice" / "ui" / "voice_button.py").read_text()


def _cpp_float(pattern: str) -> float:
    """The one float a `pattern` with a single capture group matches."""
    found = re.findall(pattern, PAINTER)
    assert found, f"no longer in mixar_audio_glyph.cc: {pattern}"
    assert len(set(found)) == 1, f"ambiguous in mixar_audio_glyph.cc: {pattern} -> {found}"
    return float(found[0])


def _cpp_color(name: str) -> tuple:
    match = re.search(rf"{name}\[4\] = \{{([^}}]*)\}}", PAINTER)
    assert match, f"colour {name} is gone from mixar_audio_glyph.cc"
    return tuple(float(part.strip().rstrip("f")) for part in match.group(1).split(","))


# -- the shapes ------------------------------------------------------------


@pytest.mark.parametrize(
    "python_value, cpp_pattern",
    [
        (raster.MIC_BODY_W, r"body_w = size \* ([0-9.]+)f"),
        (raster.MIC_BODY_H, r"body_h = size \* ([0-9.]+)f"),
        (raster.MIC_BODY_BOTTOM, r"body_bottom = cy - size \* ([0-9.]+)f"),
        (raster.MIC_CRADLE_RADIUS, r"cradle_radius = size \* ([0-9.]+)f"),
        (raster.MIC_STEM_HALF_W, r"stem\.xmax = cx \+ size \* ([0-9.]+)f"),
        (raster.STOP_HALF, r"half = size \* ([0-9.]+)f"),
        (raster.STOP_RADIUS_RATIO, r"fill_round_box\(&square, half \* ([0-9.]+)f"),
        (raster.HALO_BASE, r"size \* \(([0-9.]+)f \+ [0-9.]+f \* reach"),
        (raster.HALO_LEVEL, r"size \* \([0-9.]+f \+ ([0-9.]+)f \* reach"),
        (raster.HALO_BREATHE, r"reach \+ ([0-9.]+)f \* breathe\)"),
        (raster.HALO_ALPHA_BASE, r"([0-9.]+)f \+ [0-9.]+f \* reach\}"),
        (raster.HALO_ALPHA_LEVEL, r"[0-9.]+f \+ ([0-9.]+)f \* reach\}"),
        (raster.BREATHE_RATE, r"sinf\(pulse \* ([0-9.]+)f\)"),
        (raster.SPINNER_RADIUS, r"size \* ([0-9.]+)f,\n\s+std::max\(1\.5f"),
        (raster.SPINNER_RATE, r"pulse \* ([0-9.]+)f,\n\s+PI_F \* 1\.4f"),
        (raster.TRANSCRIBING_GHOST_ALPHA, r"COLOR_GLYPH_IDLE\[2\], ([0-9.]+)f\}"),
        (raster.PLATE_RADIUS, r"fill_round_box\(&plate, size \* ([0-9.]+)f"),
    ],
)
def test_geometry_matches_the_cpp_painter(python_value, cpp_pattern):
    assert python_value == pytest.approx(_cpp_float(cpp_pattern))


def test_the_spinner_sweep_matches():
    """Written as a multiple of pi on both sides."""
    assert "PI_F * 1.4f" in PAINTER
    assert raster.SPINNER_SWEEP == pytest.approx(3.141592653589793 * 1.4)


@pytest.mark.parametrize(
    "python_color, cpp_name",
    [
        (raster.COLOR_PLATE_IDLE, "COLOR_PLATE_IDLE"),
        (raster.COLOR_PLATE_HOVER, "COLOR_PLATE_HOVER"),
        (raster.COLOR_GLYPH_IDLE, "COLOR_GLYPH_IDLE"),
        (raster.COLOR_GLYPH_ACTIVE, "COLOR_GLYPH_ACTIVE"),
        (raster.COLOR_RECORD, "COLOR_RECORD"),
        (raster.COLOR_RECORD_PLATE, "COLOR_RECORD_PLATE"),
        (raster.COLOR_BUSY, "COLOR_BUSY"),
    ],
)
def test_palette_matches_the_cpp_painter(python_color, cpp_name):
    assert python_color == pytest.approx(_cpp_color(cpp_name))


def test_every_colour_states_its_alpha():
    """A three-value colour zero-fills alpha and draws INVISIBLE.

    The same rule the account card's palette carries, for the same reason: the
    shape simply does not appear and nothing else goes wrong.
    """
    for name, value in vars(raster).items():
        if name.startswith("COLOR_"):
            assert len(value) == 4, f"{name} must state alpha explicitly"


# -- the halo has to fit the icon cell -------------------------------------


def test_the_widest_halo_fits_inside_the_icon():
    """On the GPU surfaces the halo bleeds past its button; an icon has a cell.

    If the inset is ever loosened, the bloom is clipped to a square and the
    recording state reads as a box rather than a ring.
    """
    widest = raster.HALO_BASE + raster.HALO_LEVEL + raster.HALO_BREATHE
    assert raster.BUTTON_FILL * widest == pytest.approx(0.5)


def test_the_recording_frames_span_the_whole_halo_range():
    first = raster.recording_frame_factor(0)
    last = raster.recording_frame_factor(raster.RECORDING_FRAMES - 1)
    assert first == pytest.approx(raster.HALO_BASE)
    assert last == pytest.approx(
        raster.HALO_BASE + raster.HALO_LEVEL + raster.HALO_BREATHE
    )


def test_a_silent_recording_still_shows_a_ring():
    """The floor is what says "this is running" while nobody is speaking."""
    assert raster.halo_factor(0.0, 0.0) >= raster.HALO_BASE


def test_frame_indices_stay_in_range_for_any_input():
    for level in (-1.0, 0.0, 0.5, 1.0, 99.0):
        for pulse in (0.0, 1.7, 1234.5):
            assert 0 <= raster.recording_frame_index(level, pulse) < raster.RECORDING_FRAMES
            assert (
                0 <= raster.transcribing_frame_index(pulse) < raster.TRANSCRIBING_FRAMES
            )


# -- the rasterizer actually draws something -------------------------------


@pytest.mark.parametrize(
    "state",
    [
        raster.STATE_IDLE,
        raster.STATE_RECORDING,
        raster.STATE_TRANSCRIBING,
        raster.STATE_ERROR,
    ],
)
def test_every_state_renders_a_visible_glyph(state):
    size = 32
    pixels = raster.render_button(size, state)
    assert len(pixels) == size * size * 4
    alphas = pixels[3::4]
    assert all(0.0 <= a <= 1.0 for a in alphas)
    # A constants-only test would pass on an empty frame; this is what makes
    # the parity above mean the user sees something.
    assert sum(1 for a in alphas if a > 0.25) > 20


def test_the_mic_is_taller_than_it_is_wide():
    """The body is a capsule standing up. A square blob is not a microphone."""
    size = 48
    pixels = raster.render_button(size, raster.STATE_IDLE)
    rows = [
        y
        for y in range(size)
        if any(pixels[(y * size + x) * 4 + 3] > 0.5 for x in range(size))
    ]
    cols = [
        x
        for x in range(size)
        if any(pixels[(y * size + x) * 4 + 3] > 0.5 for y in range(size))
    ]
    assert rows and cols
    assert (rows[-1] - rows[0]) > (cols[-1] - cols[0])


def test_recording_and_idle_are_different_pictures():
    idle = raster.render_button(32, raster.STATE_IDLE)
    recording = raster.render_button(32, raster.STATE_RECORDING)
    assert idle != recording


def test_the_spinner_actually_turns():
    first = raster.render_button(
        32, raster.STATE_TRANSCRIBING, spin=raster.transcribing_frame_angle(0)
    )
    quarter = raster.render_button(
        32,
        raster.STATE_TRANSCRIBING,
        spin=raster.transcribing_frame_angle(raster.TRANSCRIBING_FRAMES // 4),
    )
    assert first != quarter


# -- no surface may drift back to a stock icon -----------------------------


def test_the_node_tile_paints_the_shared_glyph_and_not_an_icon():
    """The node tile used stock ICON_SOUND/ICON_REC/ICON_SORTTIME.

    That is what made the same control read as three different things
    depending on which surface you found it on.
    """
    assert "ED_mixar_voice_draw_button" in NODE_TILE
    assert "VoiceButtonDraw" in NODE_TILE
    for stock in ("ICON_SOUND", "ICON_REC", "ICON_SORTTIME"):
        assert stock not in NODE_TILE, f"the node tile mic fell back to {stock}"


def test_the_node_tile_samples_the_level_once_per_pass():
    """Two mics on screen must not show two levels for one recording."""
    assert NODE_TILE.count("ED_mixar_audio_level()") == 1


def test_the_chat_and_the_node_tile_call_the_same_painter():
    assert "ED_mixar_voice_draw_button" in CHAT
    assert "ED_mixar_voice_draw_button" in NODE_TILE


def test_the_npanel_prefers_the_rasterized_glyph():
    """Stock icons survive in the drawer only as the unavailable-fallback."""
    assert "glyph_icons" in DRAWER
    assert "icon_value=icon_value" in DRAWER
    tree = ast.parse(DRAWER)
    fallbacks = [
        node.targets[0].id
        for node in ast.walk(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id.endswith("_ICONS")
    ]
    assert fallbacks == ["_FALLBACK_ICONS"], (
        "the stock icon table must read as a fallback, not as the design"
    )


def test_the_icon_layer_never_raises_into_a_panel_draw():
    """A failed preview allocation costs the mic its glyph, not the tab.

    `icon_id` is called from a panel `draw()`, which runs on every mouse move;
    an exception there blanks the whole generation tab, while a 0 return is the
    drawer's documented cue to fall back to a stock icon.
    """
    from mixar.modules.voice.core import glyph_icons

    for state in (
        raster.STATE_IDLE,
        raster.STATE_RECORDING,
        raster.STATE_TRANSCRIBING,
        raster.STATE_ERROR,
    ):
        glyph_icons.icon_id(state, 0.5, 1.0)
    glyph_icons.unregister()
    # Releasing twice is what an interrupted reload does.
    glyph_icons.unregister()


def test_the_icon_layer_builds_frames_lazily_per_state():
    """~150 ms of rasterizing must not land at startup for an unpressed button."""
    source = (
        SCRIPTS / "mixar" / "modules" / "voice" / "core" / "glyph_icons.py"
    ).read_text()
    tree = ast.parse(source)
    functions = {
        node.name for node in ast.walk(tree) if isinstance(node, ast.FunctionDef)
    }
    assert "_ensure_state" in functions
    # No module-level register() to call at startup: the collection is built on
    # first read, so nothing has to remember to wire it up.
    assert "register" not in functions


def test_the_glyph_frames_are_released_on_unregister():
    """Preview collections outlive Python's module state, like the device."""
    ops = (
        SCRIPTS / "mixar" / "modules" / "voice" / "ui" / "operators" / "voice_ops.py"
    ).read_text()
    assert "glyph_icons.unregister()" in ops


def test_the_npanel_no_longer_draws_its_own_level_bar():
    """The halo carries the level now; a progress bar said it twice.

    It was also the one piece of this control that existed on no other
    surface, which is what the consistency pass was about.
    """
    assert "row.progress(" not in DRAWER
