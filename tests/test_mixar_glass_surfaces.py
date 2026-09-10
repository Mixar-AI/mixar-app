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
TOPBAR_PATH = IFACE / "interface_mixar_topbar.cc"
TOPBAR = TOPBAR_PATH.read_text(encoding="utf-8")
CINEMA_ROW_PATH = IFACE / "interface_mixar_cinema_row.cc"
CINEMA_ROW = CINEMA_ROW_PATH.read_text(encoding="utf-8")
CINEMA_VALUE_PATH = IFACE / "interface_mixar_cinema_row_value.cc"
CINEMA_VALUE = CINEMA_VALUE_PATH.read_text(encoding="utf-8")
SECTION_PATH = IFACE / "interface_mixar_section.cc"
SECTION = SECTION_PATH.read_text(encoding="utf-8")
WIDGETS_PATH = IFACE / "interface_widgets.cc"
WIDGETS = WIDGETS_PATH.read_text(encoding="utf-8")


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


class TestTheTopbarPillsArePanes:
    """The Cinema pill, the viewport shading chips and the account chip.

    All three are the same neutral capsule in the topbar, so all three take the
    PILL role and keep only their own stroke and label. The slider and the
    avatar disc are the bar's machinery and must stay flat.
    """

    def _body(self, signature: str) -> str:
        return _code(_fn_body(TOPBAR, signature))

    def test_the_three_pills_draw_the_pane(self) -> None:
        """One call per pill. A flat bed left behind keeps a hand-mixed
        near-black the material table cannot reach."""
        for signature in ("void draw_cinema_pill(", "void draw_viewport_pill(", "void draw_profile_pill("):
            assert self._body(signature).count("mixar_card_glass_round(") == 1, (
                f"{signature} no longer draws exactly one pane"
            )

    def test_no_hand_mixed_near_black_survives_the_conversion(self) -> None:
        """The three fills the panes replace are gone, not merely unused.

        A leftover token is the next edit's temptation, and the token itself
        carries the stale #0E0E0E / #050505 / #1B1B1B the design no longer
        has — the pane's capsule is the neutral.
        """
        code = _code(TOPBAR)
        for token in ("PILL_FILL", "VIEW_PILL_FILL", "PROFILE_FILL"):
            assert not re.search(rf"\b{token}\b", code), f"{token} is still a pill fill"

    def test_the_resting_cinema_pill_carries_the_hover_cue(self) -> None:
        """The fixed brightness lift went with the fill it lifted.

        Without the alpha form the resting pill has no hover or press
        feedback at all — the state changes silently.
        """
        body = self._body("void draw_cinema_pill(")
        assert "mixar_card_glass_round(&pill, rad, MIXAR_GLASS_PILL, (is_hover || pressed) ? 1.0f : 0.84f);" in body

    def test_the_lit_cinema_pill_keeps_its_opaque_green_state(self) -> None:
        """The green fill IS the state and is opaque, so it stays flat.

        Glassing it would put a pane under an opaque ramp — invisible work —
        and, worse, invite a later edit to fade the fill and lose the only
        "Cinema Mode is on" indicator there is.
        """
        body = self._body("void draw_cinema_pill(")
        lit = body[body.index("if (lit) {") : body.index("else {")]
        assert "mixar_card_glass_round(" not in lit, "the lit pill was glassed"
        assert "draw_roundbox_4fv_ex(&pill, a, b, 1.0f, nullptr, 0.0f, rad);" in lit
        assert "mixar_card_to_float(PILL_FILL_ON_A, b);" in lit
        assert "mixar_card_to_float(PILL_FILL_ON_B, a);" in lit

    def test_the_viewport_pills_alpha_dims_the_whole_pane(self) -> None:
        """Dim and lit are one alpha, so it must scale every layer.

        Handing it to a single colour instead would leave a lit-strength rim
        and gloss on a half-there chip — the piping stays, the pane goes.
        """
        body = self._body("void draw_viewport_pill(")
        assert "mixar_card_glass_round(&pill, rad, MIXAR_GLASS_PILL, alpha);" in body

    def test_each_pill_keeps_its_own_stroke(self) -> None:
        """The pane brings the family rim; these strokes are stronger.

        Dropping them would erase the difference between a resting Cinema
        pill, an active one and a shading chip — all three would be the same
        rim.
        """
        assert "mixar_card_outline_round(&pill, rad, PILL_BORDER, (is_hover || pressed) ? 1.0f : 0.85f);" in self._body(
            "void draw_cinema_pill("
        )
        assert "mixar_card_outline_round(&pill, rad, PILL_BORDER_ON," in self._body(
            "void draw_cinema_pill("
        )
        assert "mixar_card_outline_round(&pill, rad, VIEW_PILL_BORDER, alpha);" in self._body(
            "void draw_viewport_pill("
        )

    def test_the_sliders_stay_flat(self) -> None:
        """A track is a groove and a thumb is a knob.

        A glassed track shows the bar through the groove and stops reading as
        a groove; a glassed thumb stops reading as the thing that moved.
        """
        for signature in ("void draw_slider_left(", "void draw_slider_right("):
            assert "mixar_card_glass_round(" not in self._body(signature), (
                f"{signature} was glassed"
            )
        slider = self._body("void draw_slider_left(")
        assert "mixar_card_fill_round(&track, rad, SLIDER_TRACK);" in slider
        assert "mixar_card_fill_round(&thumb, rad, is_hover ? SLIDER_THUMB_HOVER : SLIDER_THUMB);" in slider

    def test_the_avatar_disc_stays_flat(self) -> None:
        """The disc is a picture, not a pane.

        Glass there shows the bar through the avatar — a hole in a face.
        """
        body = self._body("void draw_profile_pill(")
        disc = body[body.index("rctf disc;") : body.index("mixar_card_draw_text")]
        assert "mixar_card_fill_round(&disc, rad, PROFILE_AVATAR);" in disc
        assert "mixar_card_glass_round(" not in disc, "the avatar disc was glassed"

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        for call in re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(TOPBAR)):
            assert "MX_" not in call and "uchar" not in call, (
                f"a role-taking call was given a colour: {call}"
            )


class TestTheCinemaRowsArePanes:
    """The Director popups' chrome: the live row's chip and the hover fill.

    Both sit ON the popup's own back, so both take the CHIP role — the row
    with no shadow and no specular. The chip keeps the surface's graded slate
    as a translucent wash, and the hover / press cue becomes the pane's alpha.
    The slider's track and its green fill are controls and stay flat.

    The slate's token is opaque and pinned by `test_cinema_surface_fixes`, so
    the grading is softened at the call site, never in the mirror.
    """

    def _chip(self) -> str:
        return _code(_fn_body(CINEMA_ROW, "void draw_chip("))

    def test_the_live_chip_and_the_hover_fill_are_panes(self) -> None:
        assert "mixar_card_glass_round(&row, radius, MIXAR_GLASS_CHIP);" in self._chip()
        hover = _code(_fn_body(CINEMA_ROW, "void draw_hover("))
        assert "mixar_card_glass_round(&row, radius, MIXAR_GLASS_CHIP, alpha);" in hover
        assert "mixar_card_fill_round(" not in hover, (
            "the hover is still a flat grey slab, not the family material"
        )

    def test_a_row_takes_the_chip_role_and_no_other(self) -> None:
        """CARD / PANEL / ISLAND carry a shadow and a streak; a row that sits
        on the popup may cast neither, and the streak's scissor is region px
        while a row is painted in the block's coordinates."""
        code = _code(CINEMA_ROW)
        for role in (
            "MIXAR_GLASS_CARD",
            "MIXAR_GLASS_MENU",
            "MIXAR_GLASS_PANEL",
            "MIXAR_GLASS_ISLAND",
            "MIXAR_GLASS_PILL",
            "MIXAR_GLASS_CHAT",
            "MIXAR_GLASS_MOODBOARD",
        ):
            assert role not in code, f"{role} is not a row's role"
        assert code.count("MIXAR_GLASS_CHIP") == 2, "one pane per chrome primitive"

    def test_the_pane_is_laid_before_its_wash(self) -> None:
        """The wash goes over the pane; the other order hides the material."""
        chip = self._chip()
        assert chip.index("mixar_card_glass_round(") < chip.index("draw_roundbox_4fv_ex(")

    def test_the_chip_keeps_its_graded_slate_as_a_wash(self) -> None:
        """The ramp at full strength is opaque, so it would cover the pane it
        now sits on — and its token is pinned at 255, so it is softened here."""
        chip = self._chip()
        assert "mixar_card_to_float(ROW_TOP, top);" in chip
        assert "mixar_card_to_float(ROW_BOTTOM, bottom);" in chip
        assert "top[3] *= CHIP_WASH;" in chip and "bottom[3] *= CHIP_WASH;" in chip
        wash = re.search(r"^constexpr float CHIP_WASH = ([0-9.]+)f;", CINEMA_ROW, re.M)
        assert wash is not None, "the wash strength is not a named constant"
        assert 0.0 < float(wash.group(1)) < 1.0, "CHIP_WASH is not a wash"

    def test_the_wash_is_inset_so_the_rim_stays_single(self) -> None:
        """Two 1 px edges on one border read as a doubled rim."""
        chip = self._chip()
        assert "rctf wash = row;" in chip
        assert "BLI_rctf_pad(&wash, -inset, -inset);" in chip
        assert "std::max(radius - inset, 0.0f)" in chip

    def test_the_slider_track_and_the_green_fill_stay_flat(self) -> None:
        """A groove that shows the popup through it stops reading as a groove."""
        slider = _code(_fn_body(CINEMA_VALUE, "void draw_slider("))
        assert "mixar_card_glass_round(" not in slider, "the slider was glassed"
        assert "mixar_card_fill_round(&row, rad, (is_hover && !disabled) ? HOVER : TRACK, 1.0f);" in slider
        assert "mixar_card_fill_round(&fill, fill_rad, SLIDER_ON, disabled ? 0.45f : 1.0f);" in slider

    def test_no_mirrored_token_was_orphaned_by_the_conversion(self) -> None:
        """Every token still has a painter, so a later edit cannot read one as
        dead weight and delete a mirror the design still owns."""
        code = _code(CINEMA_ROW + CINEMA_VALUE)
        for token in ("ROW_TOP", "ROW_BOTTOM", "HOVER", "TRACK", "SLIDER_ON"):
            assert re.search(rf"\b{token}\b", code), f"{token} is no longer painted"

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        for src in (CINEMA_ROW, CINEMA_VALUE):
            for call in re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(src)):
                assert "MX_" not in call and "uchar" not in call, (
                    f"a role-taking call was given a colour: {call}"
                )


class TestTheCategoryTabsArePanes:
    """The panel-category strip: each tab bed, and the band it sits on.

    A tab sits ON the strip, so the bed takes the CHIP role — no shadow and no
    specular, because a chip may not cast its own (and the streak is the one
    layer the painter clips with a region-px scissor, which a tab drawn from
    the View2D's restored matrix could not place). The strip itself stays flat:
    it is a full-bleed band flush to the region edge, so it has no silhouette
    for a rim to trace and nothing for a shadow to fall on.

    The pane must also be drawn from the same rect the hit test records: the
    stub is rotated text, so a pane drawn from any other rect would render a
    click target the user cannot see.
    """

    def _tabs(self) -> str:
        return _code(_fn_body(SECTION, "void UI_panel_category_draw_all_mixar("))

    def test_the_tab_beds_are_panes(self) -> None:
        """A bed left on the theme's flat fill keeps a hand-mixed dark no
        material-table edit can reach, and drifts the moment the family is
        re-toned."""
        assert self._tabs().count("mixar_card_glass_round(") == 1, (
            "the tab bed no longer draws exactly one pane"
        )
        assert "mixar_card_glass_round(&tab_rect, tab_radius, MIXAR_GLASS_CHIP);" in self._tabs()

    def test_a_tab_takes_the_chip_role_and_no_other(self) -> None:
        """CARD / PANEL / ISLAND carry a shadow and a streak; a tab sits on the
        strip and may cast neither."""
        code = _code(SECTION)
        for role in (
            "MIXAR_GLASS_CARD",
            "MIXAR_GLASS_MENU",
            "MIXAR_GLASS_PANEL",
            "MIXAR_GLASS_ISLAND",
            "MIXAR_GLASS_PILL",
            "MIXAR_GLASS_CHAT",
            "MIXAR_GLASS_MOODBOARD",
        ):
            assert role not in code, f"{role} is not a tab's role"
        assert code.count("MIXAR_GLASS_CHIP") == 1, "one pane per tab bed"

    def test_the_pane_is_laid_before_the_designs_own_bed(self) -> None:
        """The active wash and the inactive bed go OVER the pane; the other
        order covers the very material the tab now sits in."""
        tabs = self._tabs()
        pane = tabs.index("mixar_card_glass_round(")
        assert pane < tabs.index("draw_roundbox_4fv(&tab_rect, true, tab_radius, active_bg)")
        assert pane < tabs.index("draw_roundbox_4fv(&tab_rect, true, tab_radius, col_inactive)")

    def test_the_active_tab_keeps_its_accent_wash_and_teal_outline(self) -> None:
        """The pane is the BED; the accent is the state.

        Dropping either for the neutral pane would leave the active tab
        indistinguishable from its neighbours.
        """
        tabs = self._tabs()
        assert "const float active_bg[4] = {0.0f, 192.0f / 255.0f, 199.0f / 255.0f, 0.13f};" in tabs
        assert "const float active_outline[4] = {col_accent[0], col_accent[1], col_accent[2], 0.45f};" in tabs
        assert "draw_roundbox_4fv(&tab_rect, false, tab_radius, active_outline);" in tabs

    def test_the_inactive_tab_keeps_its_bed_and_whisper_of_an_outline(self) -> None:
        """Its fill is already translucent, so it washes over the pane rather
        than needing the call-site softening the live cinema chip does."""
        tabs = self._tabs()
        assert "draw_roundbox_4fv(&tab_rect, true, tab_radius, col_inactive);" in tabs
        assert "const float outline_color[4] = {1.0f, 1.0f, 1.0f, 0.04f};" in tabs

    def test_the_strip_stays_flat_because_it_has_no_silhouette(self) -> None:
        """A band flush to the region edge gets no rim and no shadow.

        Glassing it would ring the region's own edge in the family rim and
        replace the design's 12 %-teal accent line with a bright one.
        """
        tabs = self._tabs()
        assert "draw_roundbox_4fv(&bg_rect, true, 0.0f, col_strip_bg);" in tabs
        assert "mixar_card_glass_round(" not in tabs[: tabs.index("draw_roundbox_4fv(&bg_rect")], (
            "the strip was glassed"
        )

    def test_the_tab_hit_rects_are_still_recorded(self) -> None:
        """The strip is drawn, not made of buttons, so the click map comes from
        the same rect the pane was laid in — and it is recorded every draw."""
        assert "mixar_category_tab_rects().add_overwrite(region, std::move(tab_rects));" in self._tabs()

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        calls = re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(SECTION))
        assert calls == ["&tab_rect, tab_radius, MIXAR_GLASS_CHIP"], (
            f"a role-taking call was given a colour: {calls}"
        )


class TestTheSectionCardsArePanes:
    """The grouped section card (`widget_mixar_section`), and the widgets beside
    it that must stay controls.

    The card is a surface, so its bed takes the CHIP role: a shape that sits ON
    another pane — tint, a hair of gloss, the family rim, no shadow and no
    specular. The card is painted in BLOCK coordinates, so a role with a streak
    is ruled out twice over: the painter clips that layer with a region-px
    scissor, which block coordinates cannot place. CHIP's bed is also the only
    FLAT one in the table, which is exactly what the widget's ``shaded = 0``
    exists to protect.

    The design's own #141414 bed and its 1px #262626 border are the card's
    identity, so both stay — but the bed goes back down as a WASH, because
    #141414 as designed is opaque and would cover the material the card now
    sits in.
    """

    def _card(self) -> str:
        return _code(_fn_body(WIDGETS, "static void widget_mixar_section("))

    def test_the_section_card_bed_is_a_pane(self) -> None:
        """A bed left on the theme's flat fill keeps a hand-mixed black that no
        material-table edit can reach, and drifts the moment the family is
        re-toned."""
        assert self._card().count("mixar_card_glass_round(") == 1, (
            "the section card no longer draws exactly one pane"
        )
        assert "mixar_card_glass_round(&card, rad, MIXAR_GLASS_CHIP);" in self._card()

    def test_a_section_card_takes_the_chip_role_and_no_other(self) -> None:
        """CARD / PANEL / ISLAND carry a shadow and a streak; a card in a
        column may cast neither."""
        code = _code(WIDGETS)
        for role in (
            "MIXAR_GLASS_CARD",
            "MIXAR_GLASS_MENU",
            "MIXAR_GLASS_PANEL",
            "MIXAR_GLASS_ISLAND",
            "MIXAR_GLASS_PILL",
            "MIXAR_GLASS_CHAT",
            "MIXAR_GLASS_MOODBOARD",
        ):
            assert role not in code, f"{role} is not a section card's role"
        assert code.count("MIXAR_GLASS_CHIP") == 1, "one pane per card bed"

    def test_the_pane_is_laid_before_the_designs_own_bed(self) -> None:
        """The washed #141414 bed goes OVER the pane; the other order covers
        the very material the card now sits in."""
        card = self._card()
        pane = card.index("mixar_card_glass_round(")
        assert pane < card.index("copy_v4_v4_uchar(wcol->inner, bed);")
        assert pane < card.index("widgetbase_draw(&wtb, wcol);")

    def test_the_card_keeps_its_own_black_bed_as_a_wash(self) -> None:
        """#141414 at full strength is opaque, so it is laid back at a named
        fraction — still the card's own black, over the pane."""
        card = self._card()
        assert "copy_v4_v4_uchar(bed, MX_BG);" in card
        assert "bed[3] = uchar(float(MX_BG[3]) * CARD_WASH);" in card
        assert "copy_v4_v4_uchar(wcol->inner, bed);" in card
        wash = re.search(r"constexpr float CARD_WASH = ([0-9.]+)f;", card)
        assert wash is not None, "the wash strength is not a named constant"
        assert 0.0 < float(wash.group(1)) < 1.0, "CARD_WASH is not a wash"

    def test_the_card_keeps_its_own_border_and_flat_shading(self) -> None:
        """The 1px #262626 outline is the card's own edge, and `shaded = 0`
        keeps the widget shader from gradient-filling it into a charcoal."""
        card = self._card()
        assert "copy_v4_v4_uchar(wcol->outline, MX_BORDER);" in card
        assert "wcol->shaded = 0;" in card
        assert "round_box_edges(&wtb, roundboxalign, rect, rad);" in card

    def test_the_card_still_flushes_so_its_bed_lands_on_the_pane(self) -> None:
        """The bed is queued into the widget batch, so the flush at the end is
        what puts it over the pane rather than behind it."""
        card = self._card()
        assert "widgetbase_draw_cache_flush();" in card
        assert card.index("mixar_card_glass_round(") < card.index("widgetbase_draw_cache_flush();")

    def test_the_neighbouring_widgets_stay_controls(self) -> None:
        """A toggle track, an input field, a dropdown and an action button are
        CONTROLS: a groove or a field that shows the sheet through it stops
        reading as a control."""
        for signature in (
            "static void widget_mixar_toggle(",
            "static void widget_mixar_input(",
            "static void widget_mixar_dropdown(",
            "static void widget_mixar_action_button(",
        ):
            body = _code(_fn_body(WIDGETS, signature))
            assert "mixar_card_glass_round(" not in body, f"{signature} was glassed"

    def test_no_call_site_picks_a_colour_for_the_seam(self) -> None:
        calls = re.findall(r"mixar_card_glass_round\(([^;]*)\);", _code(WIDGETS))
        assert calls == ["&card, rad, MIXAR_GLASS_CHIP"], (
            f"a role-taking call was given a colour: {calls}"
        )

