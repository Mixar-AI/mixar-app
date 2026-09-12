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
            painted = set(re.findall(r"\bMIXAR_GLASS_[A-Z]+\b", SOURCES[relpath]))
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
