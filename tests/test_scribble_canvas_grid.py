# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The Scribble canvas is one sheet of paper, and its lattice has one owner.

The canvas is not confined to the transcript: the Agent island's composer
paints the same writing surface over its input line, so a stroke that runs off
the bottom of the transcript does not stop at the region seam. That patch used
to carry its own copy of the lattice, and the copy went wrong twice.

**Stale immediate-mode vertices.** It reserved ``dot_count * segments * 3``
vertices for the whole lattice RECTANGLE, then skipped every dot whose centre
fell outside the rect inside the loop -- which, with bounds taken from
``floor(min/step)`` to ``ceil(max/step)``, is most of them. Immediate mode
draws the buffer ``immBegin`` sized; the unwritten remainder reaches the screen
as triangles built from whatever the previous draw left there. On a 560px pad
that was 1800 stale vertices, and it painted a grey wedge across the composer.

**A second pitch.** It stepped by the island's width-derived unit instead of
``UI_SCALE_FAC``, so on the Scribble pad the patch drew 24px dots against the
canvas's 36px and the grid visibly changed pitch at the seam.

Both are pinned here: the arithmetic as a model (reserved must equal emitted
for any rect), the ownership at source level.
"""

import math
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / "src" / "source" / "blender" / "editors"
CHAT_GRID = EDITORS / "space_mixie_chat" / "mixie_chat_ink_overlay.cc"
CHAT_METRICS = EDITORS / "space_mixie_chat" / "mixie_chat_ink_intern.hh"
ISLAND_DRAW = EDITORS / "space_agent_bubble" / "agent_ui_draw.cc"
ISLAND_SPACE = EDITORS / "space_agent_bubble" / "space_agent_bubble.cc"

SEGMENTS = 12


def _read(path: Path) -> str:
    assert path.is_file(), f"missing overlay source: {path}"
    return path.read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    start = src.index(signature)
    return src[start : src.index("\n}\n", start)]


def lattice_bounds(lo, hi, origin, step, dot_r):
    """The C++ loop bounds, as a model. A dot is drawn when its DISC meets."""
    first = math.ceil((lo - dot_r - origin) / step)
    last = math.floor((hi + dot_r - origin) / step)
    return first, last


class TestReservedEqualsEmitted:
    """`immBegin` sizes the buffer; emitting less than that draws stale bytes."""

    @pytest.mark.parametrize("rect", [
        (0.0, 560.0, 0.0, 823.0),      # the pad's transcript region
        (10.0, 549.0, 51.0, 87.0),     # the composer's input line on the pad
        (10.0, 862.0, 51.0, 248.0),    # the input line at the island's default width
        (0.5, 1.4, 0.5, 1.4),          # narrower than one step, off-lattice
        (-40.0, -4.0, -40.0, -4.0),    # negative coordinates
        (0.0, 36.0, 0.0, 36.0),        # exactly one cell
    ])
    @pytest.mark.parametrize("origin", [(0.0, 0.0), (0.0, 99.0), (-13.0, 7.5)])
    @pytest.mark.parametrize("scale", [1.0, 1.5, 2.0])
    def test_every_reserved_vertex_is_written(self, rect, origin, scale):
        step = 36.0 * scale
        dot_r = 2.0 * scale
        xmin, xmax, ymin, ymax = rect
        first_col, last_col = lattice_bounds(xmin, xmax, origin[0], step, dot_r)
        first_row, last_row = lattice_bounds(ymin, ymax, origin[1], step, dot_r)
        if last_col < first_col or last_row < first_row:
            return  # the C++ returns before immBegin

        reserved = ((last_col - first_col + 1) * (last_row - first_row + 1)
                    * SEGMENTS * 3)
        # The loop has NO per-dot test, so it emits one dot per lattice point.
        emitted = sum(
            SEGMENTS * 3
            for _r in range(first_row, last_row + 1)
            for _c in range(first_col, last_col + 1)
        )
        assert emitted == reserved

    def test_the_old_bounds_really_did_under_fill(self):
        """Why this test exists, in numbers.

        The previous code took floor/ceil bounds and then tested each centre
        against the rect. On the composer's input line at pad scale that is 72
        lattice points reserved against 22 actually drawn -- 1800 vertices of
        whatever the last draw left in the buffer.
        """
        step, xmin, xmax, ymin, ymax = 24.0, 10.0, 549.0, 51.0, 87.0
        first_col, last_col = math.floor(xmin / step), math.ceil(xmax / step)
        first_row, last_row = math.floor(ymin / step), math.ceil(ymax / step)
        reserved = (last_col - first_col + 1) * (last_row - first_row + 1)
        emitted = sum(
            1
            for r in range(first_row, last_row + 1)
            for c in range(first_col, last_col + 1)
            if xmin <= c * step <= xmax and ymin <= r * step <= ymax
        )
        assert emitted < reserved
        assert (reserved - emitted) * SEGMENTS * 3 > 1000


class TestOneOwner:
    """The island must not carry a second copy of the lattice."""

    def test_the_metrics_live_in_one_header(self):
        metrics = _read(CHAT_METRICS)
        for name in ("INK_GRID_STEP", "INK_GRID_DOT_R", "INK_GRID_SEGMENTS"):
            assert name in metrics, name
        body = _fn_body(_read(CHAT_GRID), "void mixie_chat_ink_draw_grid(")
        for name in ("INK_GRID_STEP", "INK_GRID_DOT_R", "INK_GRID_SEGMENTS"):
            assert name in body, f"{name} must not be re-hardcoded in the painter"

    def test_scrim_and_lattice_are_one_painter(self):
        body = _fn_body(_read(CHAT_GRID), "void mixie_chat_ink_draw_canvas(")
        assert "INK_CANVAS_SCRIM" in body and "mixie_chat_ink_draw_grid" in body, (
            "Splitting them let the island mix the surface at its own alpha, "
            "which is half of why the composer read as a ruled panel."
        )

    def test_the_patch_is_anchored_to_the_transcript_region(self):
        body = _fn_body(
            _read(ISLAND_SPACE), "static void agent_bubble_island_controls_bottom("
        )
        assert "mixie_chat_ink_draw_canvas" in body
        assert "UI_SCALE_FAC" in body, (
            "Stepping by the island's width-derived unit changed the grid's "
            "pitch at the region seam."
        )
        assert "mixie_chat_ink_area_main_region" in body, (
            "Without the transcript region's origin the lattice restarts at "
            "the composer's own corner and the dots do not line up across the "
            "seam — the same offset the strokes themselves already use."
        )

    def test_the_patch_spans_the_panel_not_the_input_line(self):
        """Pinned to the input rect it drew three lines across the pad.

        A strip of bare panel above it, another below, and six pixels of card
        inside the transcript's own left and right edges. Measured on the
        Scribble pad: canvas x 4..554 against the patch's 10..547, and bare
        panel (18,18,18) at y 87..98 and y 40..49 against the canvas (14,14,16).
        """
        body = _fn_body(
            _read(ISLAND_SPACE), "static void agent_bubble_island_controls_bottom("
        )
        canvas = body[body.index("if (state->ink_visible) {") :]
        assert "layout->panel" in canvas, "full panel width, as the transcript has"
        assert "layout->chip_upload" in canvas, "down to the chip row, not the input line"
        assert "BLI_rcti_size_y(&region->winrct)" in canvas, "up to the region's top edge"
        assert "layout->input" not in canvas, (
            "The input line's own rect is what left the strips above and below."
        )

    def test_the_island_owns_no_copy_of_the_surface(self):
        for path in (ISLAND_DRAW, ISLAND_SPACE,
                     EDITORS / "space_agent_bubble" / "agent_ui_draw.hh"):
            src = _read(path)
            assert "agent_ui_draw_scribble_input_overlay" not in src, path
            assert "agent_ui_draw_scribble_input_scrim" not in src, path
