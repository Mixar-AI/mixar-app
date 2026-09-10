# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Which Mixar surfaces become glass panes, and which stay flat.

The kit (`tests/test_mixar_liquid_glass_kit.py`) pins the material and the
painter. This file pins the CONVERSION: every surface that should adopt the
material, every control that must not, and the single seam that keeps the two
apart.

None of it can be exercised — the overlay has no `gpu` module to build against
and no compiler — so each contract below is a failure that would be invisible
until someone looked at the right widget at the right moment:

* a surface left on the flat fill keeps a raw, hand-mixed dark rectangle that
  no longer matches the family — visible only by comparing two screenshots;
* a control converted to a pane bleeds the sheet under it, and a slider track
  that shows the card through it stops reading as a groove;
* a seam that re-implements the material instead of delegating lets one
  surface drift out of the family and stops a palette edit from reaching it;
* a seam that takes a colour lets each call site pick its own tint, which is
  the drift the role table exists to prevent.

Run with the repo venv: ``python -m pytest -q`` from the repository root.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ED = ROOT / "src" / "source" / "blender" / "editors"
IFACE = ED / "interface"

CARD_PAINT_PATH = IFACE / "interface_mixar_card_paint.hh"
CARD_PAINT = CARD_PAINT_PATH.read_text(encoding="utf-8")
CARD_BUTTON_PATH = IFACE / "interface_mixar_card_button.cc"
CARD_BUTTON = CARD_BUTTON_PATH.read_text(encoding="utf-8")
PROFILE_DRAW_PATH = IFACE / "interface_mixar_profile_card_draw.cc"
PROFILE_DRAW = PROFILE_DRAW_PATH.read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    """The braced body of the first function whose text starts with
    ``signature``."""
    start = src.index(signature)
    brace = src.index("{", start)
    depth = 0
    for i in range(brace, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[brace : i + 1]
    raise AssertionError(f"unbalanced braces after {signature!r}")


def _code(src: str) -> str:
    """A file with its comments removed, so prose cannot satisfy a contract."""
    without_blocks = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", without_blocks)


class TestTheSeamIsAPaneInsteadOfAFlatFill:
    """`mixar_card_glass_round`: the one helper every surface crosses."""

    def test_the_seam_delegates_to_the_kit_and_reimplements_nothing(self) -> None:
        """A seam that drew its own roundbox would be a second material.

        It could then disagree with the role table — one surface keeps a colour
        the palette no longer has — and a table edit would silently miss it.
        """
        body = _code(_fn_body(CARD_PAINT, "inline void mixar_card_glass_round("))
        assert "mixar_glass_draw(" in body, "the seam does not call the painter"
        for forbidden in ("draw_roundbox_4fv", "draw_roundbox_corner_set", "mixar_glass_tokens"):
            assert forbidden not in body, (
                f"the seam reaches for {forbidden}; it must only hand the pane to the kit"
            )

    def test_the_seam_takes_a_role_and_never_a_colour(self) -> None:
        """A tint argument is exactly the drift the role table prevents.

        With one, two surfaces that should share a material can pick different
        darks and blur the family again — the bug the role enum was added for.
        """
        sig = CARD_PAINT[
            CARD_PAINT.index("inline void mixar_card_glass_round(") : CARD_PAINT.index(
                "inline void mixar_card_glass_round("
            )
            + 260
        ]
        sig = sig[: sig.index(")")]
        assert "eMixarGlassRole" in sig, "the seam does not name a role"
        assert "uchar" not in sig, f"the seam takes a colour: {sig}"

    def test_the_seam_hands_the_kit_region_pixels(self) -> None:
        """The kit is region-px `rcti`; the design system is `rctf`.

        Handing over an unconverted rect, or skipping the conversion, would
        draw the pane at a fractional origin the painter cannot place.
        """
        body = _fn_body(CARD_PAINT, "inline void mixar_card_glass_round(")
        assert "rcti pane;" in body
        assert "BLI_rcti_rctf_copy(&pane, rect);" in body
        assert "mixar_glass_draw(pane, style);" in body

    def test_the_seam_keeps_the_call_sites_radius(self) -> None:
        """The role's radius is the family default, not this surface's.

        A pane that ignored the passed radius would change corner on
        conversion — the same widget, a different shape.
        """
        body = _fn_body(CARD_PAINT, "inline void mixar_card_glass_round(")
        assert "style.radius = rad;" in body
        assert "style.role = role;" in body

    def test_the_seam_alpha_fades_the_whole_pane(self) -> None:
        """`alpha` is a hover lift or a fade, so it goes to the style.

        Multiplying it into a colour here would fade one layer and leave the
        rim, gloss and specular at full strength — a pane that half-disappears.
        """
        body = _code(_fn_body(CARD_PAINT, "inline void mixar_card_glass_round("))
        assert "style.alpha = alpha;" in body
        assert "c[3]" not in body, "the seam scales a colour instead of the pane"

    def test_the_flat_helpers_survive_untouched_for_controls(self) -> None:
        """The seam is additive: controls keep drawing flat shapes.

        Removing or rerouting the flat helpers would drag every slider track,
        thumb, divider and avatar disc through the pane material.
        """
        assert "inline void mixar_card_fill_round(" in CARD_PAINT
        assert "inline void mixar_card_outline_round(" in CARD_PAINT
        assert CARD_PAINT.count("inline void mixar_card_glass_round(") == 1

    def test_the_header_pulls_the_kit_in_and_explains_the_sort(self) -> None:
        assert '#include "ED_mixar_glass.hh"' in CARD_PAINT
        assert "surface" in CARD_PAINT and "control" in CARD_PAINT


class TestTheCardButtonsArePanes:
    """The four profile-card action buttons, all on one pane role.

    They sit ON the profile card, which is itself a pane, so the role is CHIP
    — the row with no shadow and no specular, whose whole purpose is a chip
    that does not double the material under it.
    """

    def _switch(self) -> str:
        return _code(_fn_body(CARD_BUTTON, "void UI_mixar_card_button_draw("))

    def test_every_variant_draws_the_pane_bed(self) -> None:
        """One glass call per variant: Accent, Danger, Ghost hover, Card."""
        assert self._switch().count("mixar_card_glass_round(") == 4, (
            "a variant still draws a flat bed and keeps a hand-mixed dark that "
            "no longer matches the family"
        )

    def test_no_raw_grey_bed_survives(self) -> None:
        """The greys the bed used to be are what the pane replaces.

        Leaving even one in place gives two buttons the same shape in two
        different materials, visible only side by side.
        """
        switch = self._switch()
        for grey in ("MX_GRAY_700", "MX_GRAY_800"):
            assert grey not in switch, f"{grey} is still a button bed"

    def test_the_accent_button_keeps_its_tint_and_stroke(self) -> None:
        """The pane is the BED; the accent wash and rim stay the button's own.

        Dropping the tint in favour of the neutral pane would silently demote
        the primary call to action to a grey chip.
        """
        switch = self._switch()
        assert "MX_ACCENT, is_hover ? 0.32f : 0.22f" in switch
        assert "MX_ACCENT, is_hover ? 0.85f : 0.55f" in switch

    def test_the_danger_button_keeps_its_tint_and_stroke(self) -> None:
        switch = self._switch()
        assert "MX_DANGER, is_hover ? 0.18f : 0.12f" in switch
        assert "MX_DANGER, is_hover ? 0.55f : 0.35f" in switch

    def test_the_ghost_button_stays_borderless_until_hovered(self) -> None:
        """Its glass call is inside the hover branch, so the resting logout
        strip keeps showing the card through it rather than a chip."""
        ghost = CARD_BUTTON[
            CARD_BUTTON.index("MixarCardElement::GhostButton: {") : CARD_BUTTON.index(
                "MixarCardElement::CardButton:"
            )
        ]
        assert re.search(
            r"if \(is_hover\) \{\s*mixar_card_glass_round\(&box, rad, MIXAR_GLASS_CHIP\);",
            _code(ghost),
        ), "the GhostButton paints at rest"

    def test_the_plain_button_keeps_its_border_and_a_hover_cue(self) -> None:
        """Its bed carries no colour, so hover must show in the pane's alpha."""
        switch = self._switch()
        assert "mixar_card_outline_round(&box, rad, MX_BORDER_STRONG, 1.0f)" in switch
        assert "MIXAR_GLASS_CHIP, is_hover ? 1.0f : 0.85f" in switch, (
            "the plain card button lost its only hover cue with the grey bed"
        )

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        for call in re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(CARD_BUTTON)):
            assert "MX_" not in call and "uchar" not in call, (
                f"a role-taking call was given a colour: {call}"
            )


class TestTheProfilePlanChipIsAPane:
    """The plan chip on the account card, and the shapes beside it that are not.

    The chip NAMES the current plan; it sets nothing. So it joins the glass
    under the CHIP role — the row for a shape that sits on another pane. The
    divider and the quota bar are the card's machinery and must stay flat.
    """

    def _pill(self) -> str:
        return _code(_fn_body(PROFILE_DRAW, "void draw_pill("))

    def test_the_chip_bed_is_the_pane(self) -> None:
        """A chip left on `MX_GRAY_800` keeps a hand-mixed dark no table edit
        can reach, and drifts the moment the family is re-toned."""
        pill = self._pill()
        assert "mixar_card_glass_round(&chip, rad, MIXAR_GLASS_CHIP);" in pill, (
            "the plan chip still draws a flat, hand-mixed bed"
        )

    def test_no_raw_grey_bed_survives_on_the_chip(self) -> None:
        pill = self._pill()
        for grey in ("MX_GRAY_700", "MX_GRAY_800"):
            assert grey not in pill, f"{grey} is still the chip's bed"

    def test_the_chip_keeps_its_own_stroke(self) -> None:
        """The pane brings the family rim; the chip's stroke is stronger.

        Dropping it would leave the chip outlined only by the family rim and
        no longer distinguishable from any other chip on the card.
        """
        pill = self._pill()
        assert "mixar_card_outline_round(&chip, rad, MX_BORDER_STRONG, 1.0f);" in pill, (
            "the chip lost the stroke that separates it from the card"
        )

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        for call in re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(PROFILE_DRAW)):
            assert "MX_" not in call and "uchar" not in call, (
                f"a role-taking call was given a colour: {call}"
            )

    def test_the_card_machinery_stays_flat(self) -> None:
        """The divider and the quota bar are controls: a groove and a gauge.

        Showing the card through a divider stops it reading as a separator,
        and a glassed track or fill makes the quota ambiguous — the reading
        the flat ramp exists to make unmistakable.
        """
        divider = _code(_fn_body(PROFILE_DRAW, "void draw_divider("))
        usage = _code(_fn_body(PROFILE_DRAW, "void draw_usage_bar("))
        for name, body in (("draw_divider", divider), ("draw_usage_bar", usage)):
            assert "mixar_card_glass_round(" not in body, f"{name} was glassed"
        assert "mixar_card_fill_round(&line, 0.0f, MX_BORDER_STRONG)" in divider
        assert "mixar_card_fill_round(&track, rad, MX_BG_SUNKEN)" in usage
        assert "fill_ramp(&fill, rad, CARD_USAGE_RAMP_START, CARD_USAGE_RAMP_END)" in usage

