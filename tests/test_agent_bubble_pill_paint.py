# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The pill's window IS the capsule, so nothing it paints may fall outside it.

That identity is load-bearing three times over: it is what lets the corners be
transparent (``Mixar_WindowSetPerPixelAlpha`` -- see
``test_agent_bubble_window_shape.py``), what makes the hit area exactly the
shape the user sees, and what the seat geometry anchors and drags. The window
therefore cannot be grown to make room for decoration.

Anything drawn outside the pill rect is silently clipped: no error, no warning,
and on a translucent effect not even a visible absence -- it simply never
appears while costing a draw call per frame. The "breathing halo" was the
capsule INFLATED by three units and was clipped in its entirety. Measured on
the running app under the QA harness: the capsule occupied rows 1019..1072 in
the idle frame and in all three busy frames, and the pixel immediately outside
it was bare background in every one.

Pinned at source level because the failure is invisible at runtime -- there is
nothing to assert on a pixel that was never drawn.
"""

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PILL_DRAW = (
    ROOT / "src" / "source" / "blender" / "editors" / "space_agent_bubble" / "agent_ui_draw.cc"
)


def _fn_body(src: str, signature: str) -> str:
    start = src.index(signature)
    return src[start : src.index("\n}\n", start)]


@pytest.fixture(scope="module")
def pill_body() -> str:
    src = PILL_DRAW.read_text(encoding="utf-8")
    return _fn_body(src, "void agent_ui_draw_status_pill(")


class TestNothingIsPaintedOutsideTheWindow:
    def test_no_rect_derived_from_the_pill_grows_outward(self, pill_body: str) -> None:
        """`rect.xmin -= …` / `rect.ymax += …` push a shape past the window.

        Insetting (``xmin +=`` / ``xmax -=``) is how a shape stays inside, so
        the outward form is the one that has to be absent. The pill draws
        several rects derived from its own bounds; this catches any of them
        being expanded rather than inset.
        """
        outward = re.findall(
            r"^\s*\w+\.(?:xmin|ymin)\s*-=|^\s*\w+\.(?:xmax|ymax)\s*\+=",
            pill_body,
            re.MULTILINE,
        )
        assert outward == [], (
            "A rect derived from the pill is being grown past the window, "
            "where it is clipped away with no signal of any kind: "
            f"{outward}"
        )

    def test_the_working_glow_is_inset(self, pill_body: str) -> None:
        glow = pill_body[pill_body.index("if (is_working) {") :]
        glow = glow[: glow.index("Pulsing animated green rim")]
        assert "glow.xmin += glow_pad;" in glow and "glow.xmax -= glow_pad;" in glow
        assert "(h * 0.5f) - glow_pad" in glow, (
            "The radius has to shrink with the rect or the inset capsule's "
            "ends stop being semicircles."
        )

    def test_the_radius_never_exceeds_half_the_short_side(self, pill_body: str) -> None:
        """A capsule's radius is half its height; more than that is not a shape.

        `UI_draw_roundbox` clamps, so an over-large radius is not a crash --
        it is a silently different silhouette, which is worse.
        """
        for radius in re.findall(r"outline_round\(&\w+,\s*([^,]+),", pill_body):
            radius = radius.strip()
            assert "+ glow_pad" not in radius and "+ halo_pad" not in radius, radius
