# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

from .surface_contracts import (
    CINEMA_ROW,
    CINEMA_VALUE,
    SECTION,
    TOPBAR,
    _code,
    _fn_body,
    re,
)


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
        assert "mixar_card_to_float(mixar_chrome::cinema_pill_fill_on_a, b);" in lit
        assert "mixar_card_to_float(mixar_chrome::cinema_pill_fill_on_b, a);" in lit

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
        rim. Colours live in `UI_mixar_chrome.hh`.
        """
        assert "mixar_card_outline_round(&pill, rad, mixar_chrome::cinema_pill_border, (is_hover || pressed) ? 1.0f : 0.85f);" in self._body(
            "void draw_cinema_pill("
        )
        assert "mixar_card_outline_round(&pill, rad, mixar_chrome::cinema_pill_border_on," in self._body(
            "void draw_cinema_pill("
        )
        assert "mixar_card_outline_round(&pill, rad, mixar_chrome::viewport_pill_border, alpha);" in self._body(
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
        assert "mixar_card_fill_round(&track, rad, mixar_chrome::slider_track);" in slider
        assert "mixar_card_fill_round(&thumb, rad, is_hover ? mixar_chrome::slider_thumb_hover : mixar_chrome::slider_thumb);" in slider

    def test_the_avatar_disc_stays_flat(self) -> None:
        """The disc is a picture, not a pane.

        Glass there shows the bar through the avatar — a hole in a face.
        """
        body = self._body("void draw_profile_pill(")
        disc = body[body.index("rctf disc;") : body.index("mixar_card_draw_text")]
        assert "mixar_card_fill_round(&disc, rad, mixar_chrome::profile_avatar);" in disc
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
        """Rows use CHIP's quiet material without a separate shadow."""
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
    specular, keeping the control quiet. The strip itself stays flat:
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
