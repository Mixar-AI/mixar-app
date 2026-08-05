# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Scribble rasterizer: framing, the y flip, and pressure-weighted strokes.

The payload arrives in Blender region coordinates (y **up**) and images are
y-down, so the flip is the one thing here that is silently invertible — a
mirrored page still renders, still uploads, and comes back as nonsense. The
assertions below pin the direction explicitly rather than by symmetry.
"""

import importlib
import io
import os
import sys
from unittest.mock import MagicMock

import pytest

_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))

for _name in ("keyring", "keyring.errors"):
    sys.modules.setdefault(_name, MagicMock(name=_name))

from mixar.modules.space_mixie_chat.core import scribble_raster  # noqa: E402
from mixar.modules.space_mixie_chat.core.scribble_raster import (  # noqa: E402
    raster_geometry,
    rasterize_strokes,
    segment_width,
)
from mixar.modules.space_mixie_chat.constants import (  # noqa: E402
    SCRIBBLE_RASTER_MIN_EDGE,
    SCRIBBLE_RASTER_PADDING,
)


_PIL_MODULES = ("PIL", "PIL.Image", "PIL.ImageDraw")


def _load_real_pillow():
    """Import the genuine Pillow past the shared bpy stub.

    ``pytest.importorskip("PIL")`` is not enough: ``modules/testing/mock_bpy``
    (pulled in by the ``tests/`` suite, which the default run collects first)
    registers ``PIL`` as a MagicMock. The import then succeeds and every
    rendered page comes back a mock that satisfies any assertion made about
    it — so the rendering tests would pass without rendering anything.

    The stub is restored before returning; the ``pillow`` fixture swaps the
    real modules in only for the tests that draw. Returns None when Pillow
    genuinely is not installed.
    """
    stubbed = {
        name: module for name, module in sys.modules.items()
        if name == "PIL" or name.startswith("PIL.")
    }
    for name in stubbed:
        del sys.modules[name]
    try:
        real = {name: importlib.import_module(name) for name in _PIL_MODULES}
    except ImportError:
        real = None
    finally:
        for name in [n for n in sys.modules
                     if n == "PIL" or n.startswith("PIL.")]:
            del sys.modules[name]
        sys.modules.update(stubbed)
    return real


_REAL_PILLOW = _load_real_pillow()


@pytest.fixture
def pillow(monkeypatch):
    """Real ``PIL.Image``, with the real Pillow installed for this test only."""
    if _REAL_PILLOW is None:
        pytest.skip("Pillow is not installed")
    for name, module in _REAL_PILLOW.items():
        monkeypatch.setitem(sys.modules, name, module)
    return _REAL_PILLOW["PIL.Image"]


# A diagonal from the payload's bottom-left to its top-right. Deliberately
# asymmetric in both axes so a flipped or transposed page fails.
DIAGONAL = {
    "w": 400,
    "h": 300,
    "strokes": [[(0.0, 0.0, 1.0), (50.0, 50.0, 1.0), (100.0, 100.0, 1.0)]],
}


def render(pillow, payload, max_edge=200):
    return pillow.open(io.BytesIO(rasterize_strokes(payload, max_edge=max_edge)))


def dark_pixels(image, threshold=128):
    """Count of pixels darker than *threshold* on an "L" page."""
    return sum(image.histogram()[:threshold])


class TestGeometry:
    def test_longest_edge_scales_to_max_edge(self):
        payload = {"w": 800, "h": 600,
                   "strokes": [[(100.0, 50.0, 1.0), (300.0, 150.0, 1.0)]]}
        geom = raster_geometry(payload, max_edge=1280)
        # Ink box is 200 x 100 -> scale 6.4, plus the padding on both sides.
        # (pytest.approx is unusable in this suite: the shared bpy stub
        # registers a mock ``numpy``, which its bool check chokes on.)
        assert abs(geom.scale - 6.4) < 1e-9
        assert geom.width == 1280 + 2 * SCRIBBLE_RASTER_PADDING
        assert geom.height == 640 + 2 * SCRIBBLE_RASTER_PADDING

    def test_small_writing_is_upscaled(self):
        # Legibility, not fidelity: a signature scribbled in one corner of a
        # big region must still fill the page.
        payload = {"w": 800, "h": 600,
                   "strokes": [[(10.0, 10.0, 1.0), (20.0, 15.0, 1.0)]]}
        geom = raster_geometry(payload, max_edge=1280)
        assert geom.scale > 1.0
        assert geom.width == 1280 + 2 * SCRIBBLE_RASTER_PADDING

    def test_ink_is_inset_by_the_padding(self):
        geom = raster_geometry(DIAGONAL, max_edge=200)
        x, y = geom.project(0.0, 100.0)
        assert abs(x - SCRIBBLE_RASTER_PADDING) < 1e-9
        assert abs(y - SCRIBBLE_RASTER_PADDING) < 1e-9

    def test_projection_flips_y(self):
        geom = raster_geometry(DIAGONAL, max_edge=200)
        top = geom.project(0.0, 100.0)      # highest payload y
        bottom = geom.project(0.0, 0.0)     # lowest payload y
        assert top[1] < bottom[1]

    def test_x_is_not_flipped(self):
        geom = raster_geometry(DIAGONAL, max_edge=200)
        assert geom.project(0.0, 0.0)[0] < geom.project(100.0, 0.0)[0]

    def test_single_point_gives_a_floored_square_with_the_dot_centred(self):
        # A lone tap has no extent: its natural page (2*pad square) is under
        # the backend's 64px upload floor, so both axes floor to
        # SCRIBBLE_RASTER_MIN_EDGE with the dot dead centre.
        payload = {"w": 800, "h": 600, "strokes": [[(42.0, 99.0, 1.0)]]}
        geom = raster_geometry(payload, max_edge=200)
        assert (geom.width, geom.height) == (SCRIBBLE_RASTER_MIN_EDGE,) * 2
        assert geom.project(42.0, 99.0) == (SCRIBBLE_RASTER_MIN_EDGE / 2.0,
                                            SCRIBBLE_RASTER_MIN_EDGE / 2.0)

    def test_thin_horizontal_stroke_floors_the_height(self):
        # A single dash: 2000x2 of ink scales to a ~1280x1 sliver, which the
        # backend's validate_image would 400-reject. The height floors to
        # SCRIBBLE_RASTER_MIN_EDGE with the ink centred vertically; the
        # already-large width is untouched.
        payload = {"w": 2400, "h": 1400,
                   "strokes": [[(0.0, 50.0, 1.0), (2000.0, 52.0, 1.0)]]}
        geom = raster_geometry(payload, max_edge=1280)
        assert geom.width == 1280 + 2 * SCRIBBLE_RASTER_PADDING
        assert geom.height == SCRIBBLE_RASTER_MIN_EDGE
        assert geom.offset_x == 0.0
        assert geom.offset_y > 0.0
        mid_y = geom.project(1000.0, 51.0)[1]
        assert abs(mid_y - geom.height / 2.0) < geom.height * 0.25

    def test_thin_vertical_stroke_floors_the_width(self):
        payload = {"w": 2400, "h": 1400,
                   "strokes": [[(300.0, 0.0, 1.0), (302.0, 1200.0, 1.0)]]}
        geom = raster_geometry(payload, max_edge=1280)
        assert geom.height == 1280 + 2 * SCRIBBLE_RASTER_PADDING
        assert geom.width == SCRIBBLE_RASTER_MIN_EDGE
        assert geom.offset_y == 0.0
        assert geom.offset_x > 0.0
        mid_x = geom.project(301.0, 600.0)[0]
        assert abs(mid_x - geom.width / 2.0) < geom.width * 0.25

    def test_no_ink_raises(self):
        with pytest.raises(ValueError):
            raster_geometry({"w": 10, "h": 10, "strokes": []})


class TestRasterizedPixels:
    def test_page_is_grayscale_and_sized_from_the_geometry(self, pillow):
        image = render(pillow, DIAGONAL)
        geom = raster_geometry(DIAGONAL, max_edge=200)
        assert image.mode == "L"
        assert image.size == (geom.width, geom.height)

    def test_high_payload_y_lands_near_the_top_of_the_image(self, pillow):
        image = render(pillow, DIAGONAL)
        geom = raster_geometry(DIAGONAL, max_edge=200)
        top_right = geom.project(100.0, 100.0)     # payload's highest point
        bottom_left = geom.project(0.0, 0.0)
        assert image.getpixel((int(top_right[0]) - 1, int(top_right[1]) + 1)) < 128
        assert image.getpixel((int(bottom_left[0]) + 1,
                               int(bottom_left[1]) - 1)) < 128
        # The other two corners are on the far side of the diagonal.
        assert image.getpixel((SCRIBBLE_RASTER_PADDING, SCRIBBLE_RASTER_PADDING)) > 200
        assert image.getpixel((geom.width - SCRIBBLE_RASTER_PADDING,
                               geom.height - SCRIBBLE_RASTER_PADDING)) > 200

    def test_single_point_stroke_draws_a_dot(self, pillow):
        payload = {"w": 800, "h": 600, "strokes": [[(42.0, 99.0, 1.0)]]}
        image = render(pillow, payload)
        centre = SCRIBBLE_RASTER_MIN_EDGE // 2  # floored square, dot centred
        assert image.getpixel((centre, centre)) < 128
        assert dark_pixels(image) > 0

    def test_thin_stroke_page_meets_the_upload_floor(self, pillow):
        # The rendered PNG itself (not just the geometry) must satisfy the
        # backend's 64x64 validate_image floor, with the ink visible on the
        # floored axis.
        payload = {"w": 2400, "h": 1400,
                   "strokes": [[(0.0, 50.0, 1.0), (2000.0, 52.0, 1.0)]]}
        image = render(pillow, payload, max_edge=1280)
        assert image.size[0] >= SCRIBBLE_RASTER_MIN_EDGE
        assert image.size[1] == SCRIBBLE_RASTER_MIN_EDGE
        assert image.getpixel((image.size[0] // 2, image.size[1] // 2)) < 128

    def test_output_is_a_png(self, pillow):
        assert rasterize_strokes(DIAGONAL, max_edge=200)[:8] == b"\x89PNG\r\n\x1a\n"


class TestPressure:
    def test_segment_width_is_monotonic(self):
        widths = [segment_width(20, p) for p in (0.0, 0.25, 0.5, 0.75, 1.0)]
        assert widths == sorted(widths)
        assert widths[0] < widths[-1]

    def test_segment_width_clamps_out_of_range_pressure(self):
        assert segment_width(20, -3.0) == segment_width(20, 0.0)
        assert segment_width(20, 7.0) == segment_width(20, 1.0)

    def test_segment_width_never_vanishes(self):
        assert segment_width(1, 0.0) >= 1

    def test_heavier_pressure_lays_down_more_ink(self, pillow):
        def line(pressure):
            return {"w": 400, "h": 300,
                    "strokes": [[(0.0, 50.0, pressure), (100.0, 50.0, pressure)]]}

        assert (dark_pixels(render(pillow, line(1.0)))
                > dark_pixels(render(pillow, line(0.1))))


class TestUnavailablePillow:
    def test_missing_pillow_raises_a_typed_error(self, monkeypatch):
        # Pillow ships with Mixar's embedded Python; this only guards a
        # broken install, and must not surface as a bare ImportError.
        monkeypatch.setitem(sys.modules, "PIL", None)
        monkeypatch.setitem(sys.modules, "PIL.Image", None)
        with pytest.raises(scribble_raster.RasterizerUnavailableError):
            rasterize_strokes(DIAGONAL, max_edge=200)
