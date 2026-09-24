# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

from .surface_contracts import (
    KIT_FILES,
    PANE_CALLS,
    PANE_ENTRY_POINTS,
    SOURCES,
    UNPAINTED_ROLES,
    WIDGETS,
    _code,
    _fn_body,
    re,
)


class TestTheSectionCardsArePanes:
    """The grouped section card (`widget_mixar_section`), and the widgets beside
    it that must stay controls.

    The card is a surface, so its bed takes the CHIP role: a shape that sits ON
    another pane — tint, a hair of gloss, the family rim, no shadow and no
    specular. CHIP's bed is also the only
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
        column may cast neither. The Zen toolbar's PILL pane lives in the
        same file and is not this card."""
        code = self._card()
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
        assert "copy_v4_v4_uchar(bed, bg_u);" in card
        assert "bed[3] = uchar(float(bg_u[3]) * CARD_WASH);" in card
        assert "copy_v4_v4_uchar(wcol->inner, bed);" in card
        wash = re.search(r"constexpr float CARD_WASH = ([0-9.]+)f;", card)
        assert wash is not None, "the wash strength is not a named constant"
        assert 0.0 < float(wash.group(1)) < 1.0, "CARD_WASH is not a wash"

    def test_the_card_keeps_its_own_border_and_flat_shading(self) -> None:
        """The 1px #262626 outline is the card's own edge, and `shaded = 0`
        keeps the widget shader from gradient-filling it into a charcoal."""
        card = self._card()
        assert "copy_v4_v4_uchar(wcol->outline, widget_border);" in card
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
        assert calls == [
            "&card, rad, MIXAR_GLASS_CHIP",
        ], f"a role-taking call was given a colour: {calls}"

    def test_zen_toolbar_tools_are_one_pill_pane(self) -> None:
        """Move / Rotate / Scale stay `ToolbarItem` so `but_is_tool` still
        picks icon size. The aligned column is ONE PILL pane — the same
        0.20 wash and tint-off sheen/rim as the minimised chat capsule.
        Selected is a circular zen.selected chip so the active cell
        reads on the dark PILL; a 10% outer-corner wash disappeared."""
        body = _code(_fn_body(WIDGETS, "static void widget_zen_tool_glass("))
        assert "but->alignnr" in body
        assert "BLI_rctf_union(&uni, &other.rect)" in body
        assert "mixar_glass_tokens(MIXAR_GLASS_PILL)" in body
        assert "0.20f" in body
        assert "style.draw_tint = floats_over_content" in body
        assert "mixar_glass_draw(pane_i, style)" in body
        assert "MIXAR_GLASS_CHIP" not in body
        assert "mixar_tokens::mixar_zen().selected" in body
        assert "0.88f" in body
        assert "draw_roundbox_corner_set(CNR_ALL)" in body
        icons = _code(_fn_body(WIDGETS, "static void widget_draw_icon("))
        assert "zen_glass_cell(but)" in icons
        exec_body = _code(_fn_body(WIDGETS, "static void widget_roundbut_exec("))
        assert "widget_zen_tool_glass(but, rect, state, roundboxalign)" in exec_body
        assert "zen_glass_cell(but)" in exec_body
        assert "wtb.draw_inner = false;" in exec_body

    def test_a_wide_zen_toolbar_cell_clamps_to_a_square(self) -> None:
        """A tools-region column stretches these buttons to the region width.
        The capsule radius is half the short side, so a wide short cell paints
        a horizontal bar and the glyph sits on its left. Clamping the draw
        rect to a square anchored on that edge keeps the pane, the selected
        wash and the icon on the same footprint. Header shading rows are wider
        than they are tall on purpose, so the clamp is toolbar-tools only."""
        body = _code(_fn_body(WIDGETS, "static void widget_zen_tool_glass("))
        clamp = body[: body.index("rctf pane;")]
        assert "if (zen_toolbar_tool(but))" in clamp
        assert "w > h && h > 0" in clamp
        assert "rect->xmax = rect->xmin + h;" in clamp
        icons = _code(_fn_body(WIDGETS, "static void widget_draw_text_icon("))
        assert "is_tool && !zen_toolbar_tool(but)" in icons

    def test_explicit_glass_tool_capsules_take_the_readability_floor(self) -> None:
        """The 0.20 wash is calibrated for the viewport transform strip, whose
        only backdrop is the 3D view. An explicit GLASS_TOOL capsule floats
        over content the pane cannot predict — the Zen moodboard drawer's
        add-tools sit on reference photography — so it skips the manual wash
        and lets the shader apply PILL's `fallback_alpha`. Measured over a
        bright card the wash separated the bed from the image behind it by
        1.14:1 and left the icons at 2.75:1; the floor gives 2.83:1 and
        4.71:1."""
        body = _code(_fn_body(WIDGETS, "static void widget_zen_tool_glass("))
        assert "but->mixar_style.component == MixarComponent::GlassTool" in body
        assert "if (!floats_over_content) {" in body
        assert "style.draw_tint = floats_over_content" in body
        # The wash must remain the branch the transform strip takes.
        wash = body[body.index("if (!floats_over_content) {"):]
        assert "0.20f" in wash[:wash.index("}")]

    def test_zen_glass_covers_header_shading_icons(self) -> None:
        """The header strip retains native RNA enum buttons.

        `but_is_tool` would miss them and leave the four shading icons on
        the stock radio/exec slab. Membership still refuses Mixar
        Action/Segment buttons so a Zen aligned row of those stays theirs.
        """
        body = _code(_fn_body(WIDGETS, "static bool zen_glass_cell(const Button *but)\n{"))
        assert "zen_toolbar_tool(but)" in body
        assert "ButtonType::Row" in body
        assert "drawstr.empty()" in body
        assert "MixarComponent::None" in body
        union = _code(_fn_body(WIDGETS, "static void widget_zen_tool_glass("))
        assert "zen_glass_cell(&other)" in union
        assert "BUT_ALIGN_RIGHT" in union
        assert "ELEM(but->type, ButtonType::Row, ButtonType::Popover) && zen_glass_cell(but)" in WIDGETS
        assert "widget_zen_tool_glass(but, rect, &state, roundboxalign)" in WIDGETS


class TestEverySurfaceThatReachesThePainterIsOnTheRegister:
    """The sweep's boundary, in one place.

    The conversion lands a few surfaces at a time, and each commit has to be
    reviewable alone — which means nothing else states what the family already
    covers. Without that list a later sweep can double-convert a control (a
    slider track that shows the card through it stops reading as a groove) or
    leave a surface on a hand-mixed fill that no longer matches the family, and
    both are invisible until two builds are compared by eye.

    The register is a contract, not a snapshot: the viewport's context menus
    are still to come, and that commit must add its file and its role here,
    because these tests fail until it does.
    """

    def _drawers(self) -> set[str]:
        return {
            relpath
            for relpath, src in SOURCES.items()
            if relpath.endswith(".cc")
            and any(entry in src for entry in PANE_ENTRY_POINTS)
        }

    def test_every_file_that_reaches_the_painter_is_registered(self) -> None:
        """A file off the register is a conversion that skipped its commit.

        It is also the only warning there will be: the surface looks fine by
        itself, and only the register says whether it belongs to the family.
        """
        assert self._drawers() == set(PANE_CALLS), (
            "files reach the painter off the register: "
            f"{sorted(self._drawers() ^ set(PANE_CALLS))}"
        )

    def test_each_registered_file_paints_the_role_the_register_names(self) -> None:
        """The role IS the surface's colour, rim and shadow budget.

        A surface switched to another role silently changes material: the pane
        keeps rendering, the tweak was made for a reason, and only the register
        records which role the design gave it.
        """
        for relpath, roles in PANE_CALLS.items():
            painted = set(re.findall(r"\bMIXAR_GLASS_[A-Z_]+\b", SOURCES[relpath]))
            assert painted == set(roles), (
                f"{relpath} paints {sorted(painted)}, register says {sorted(roles)}"
            )

    def test_the_unpainted_roles_stay_inside_the_kit(self) -> None:
        """MENU is declared ahead of its surface.

        Viewport context menus have no pane yet, so that role may appear
        only in the header that enumerates it and the table that gives it a
        row — a role painted from anywhere else is a conversion that did
        not stand on its own.
        """
        for role in UNPAINTED_ROLES:
            holders = {relpath for relpath, src in SOURCES.items() if role in src}
            assert holders <= KIT_FILES, (
                f"{role} is painted outside the kit: {sorted(holders - KIT_FILES)}"
            )
