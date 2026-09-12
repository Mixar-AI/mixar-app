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
  the drift the role table exists to prevent;
* a sweep that keeps no register of what it has covered lets a later pass
  convert a surface twice or miss one, and neither shows up until two builds
  are compared by eye.

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
CHAT = ED / "space_mixie_chat"
CHAT_INTERN = (CHAT / "mixie_chat_intern.hh").read_text(encoding="utf-8")
CHAT_PRIMITIVES = (CHAT / "mixie_chat_ui_primitives.cc").read_text(encoding="utf-8")
CHAT_WIDGETS = (CHAT / "mixie_chat_ui_widgets.cc").read_text(encoding="utf-8")
CHAT_CONTENT = (CHAT / "mixie_chat_messages_content.cc").read_text(encoding="utf-8")
CHAT_RENDER = (CHAT / "mixie_chat_messages_render.cc").read_text(encoding="utf-8")
AGENT = ED / "space_agent_bubble"
AGENT_THEME = (AGENT / "agent_ui_theme.hh").read_text(encoding="utf-8")
AGENT_LAYOUT_HH = (AGENT / "agent_ui_layout.hh").read_text(encoding="utf-8")
AGENT_LAYOUT = (AGENT / "agent_ui_layout.cc").read_text(encoding="utf-8")
AGENT_DRAW = (AGENT / "agent_ui_draw.cc").read_text(encoding="utf-8")


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


def _overlay_sources() -> dict[str, str]:
    """The overlay's editors tree, comment-stripped, by path relative to ``ED``.

    ``src/`` holds only the files the overlay adds or replaces, so this is
    every surface that can reach the painter — not the whole of Blender. The
    comments go because the register below is about what the code does, and
    the sweep's own prose names roles it has already painted.
    """
    return {
        path.relative_to(ED).as_posix(): _code(path.read_text(encoding="utf-8"))
        for path in sorted(ED.rglob("*"))
        if path.suffix in {".cc", ".hh"}
    }


SOURCES = _overlay_sources()

# The five ways a surface asks the family for a pane: the seam every Mixar
# surface crosses, the painter itself, and the three per-tree wrappers whose
# call sites live outside `blender::ui`.
PANE_ENTRY_POINTS = (
    "mixar_card_glass_round(",
    "mixar_glass_draw(",
    "moodboard_draw_glass_pane(",
    "glass_fill_round(",
    "glass_pane(",
)

# The register: every file that reaches the painter, and the role literals it
# hands over. The painter draws the role it is given, so it names none. A
# conversion lands its file here in the same commit.
PANE_CALLS = {
    "interface/interface_mixar_liquid_glass_draw.cc": (),
    "interface/interface_mixar_topbar.cc": ("MIXAR_GLASS_PILL",),
    "interface/interface_mixar_zen_chrome.cc": ("MIXAR_GLASS_ISLAND",),
    "space_view3d/view3d_director_cinema_paint.cc": ("MIXAR_GLASS_CARD",),
    "interface/interface_mixar_card_button.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_profile_card_draw.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_cinema_row.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_mixar_section.cc": ("MIXAR_GLASS_CHIP",),
    "interface/interface_widgets.cc": ("MIXAR_GLASS_CHIP",),
    "space_agent_bubble/agent_ui_draw.cc": ("MIXAR_GLASS_CARD", "MIXAR_GLASS_PILL"),
    "space_view3d/view3d_agent_panel_draw.cc": ("MIXAR_GLASS_PANEL",),
    "space_mixie/mixie_draw_moodboard.cc": ("MIXAR_GLASS_MOODBOARD",),
    "space_mixie/mixie_draw_moodboard_graph.cc": (),
    "space_mixie/mixie_draw_moodboard_node_ui.cc": (),
    "space_mixie_chat/mixie_chat_ui_primitives.cc": ("MIXAR_GLASS_CHAT",),
    "space_mixie_chat/mixie_chat_ui_widgets.cc": (),
    "space_mixie_chat/mixie_chat_messages_content.cc": (),
}

# The family declares eight roles; seven have a surface. MENU is the queue.
UNPAINTED_ROLES = (
    "MIXAR_GLASS_MENU",
)

# The kit: the header that enumerates the roles, the table that gives each a
# row, the painter, the backdrop chain and the seam. A role with no surface
# may live here and nowhere else.
KIT_FILES = {
    "include/ED_mixar_glass.hh",
    "interface/interface_mixar_card_paint.hh",
    "interface/interface_mixar_liquid_glass.cc",
    "interface/interface_mixar_liquid_glass_draw.cc",
    "interface/interface_mixar_liquid_glass_tokens.cc",
}


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

    def test_the_seam_disables_specular_for_controls(self) -> None:
        """Controls keep a quiet material without a moving highlight."""
        body = _code(_fn_body(CARD_PAINT, "inline void mixar_card_glass_round("))
        assert "style.draw_specular = false;" in body

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
        the primary call to action to a grey chip. Alphas live in
        `UI_mixar_chrome.hh` so the card and every other accent surface stay in step.
        """
        switch = self._switch()
        assert "MX_ACCENT," in switch
        assert "mixar_chrome::card_accent_fill_hover" in switch
        assert "mixar_chrome::card_accent_fill" in switch
        assert "mixar_chrome::card_accent_outline_hover" in switch
        assert "mixar_chrome::card_accent_outline" in switch

    def test_the_danger_button_keeps_its_tint_and_stroke(self) -> None:
        switch = self._switch()
        assert "MX_DANGER," in switch
        assert "mixar_chrome::card_danger_fill_hover" in switch
        assert "mixar_chrome::card_danger_fill" in switch
        assert "mixar_chrome::card_danger_outline_hover" in switch
        assert "mixar_chrome::card_danger_outline" in switch

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
        assert "mixar_card_outline_round(&box, rad, MX_BORDER_STRONG, mixar_chrome::card_outline)" in switch
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


class TestTheChatMessagePillIsAPane:
    """The user's own message (`mixie_chat_render_message_content`), and the
    blocks that share its fill but must stay flat.

    The message area draws through ``ui::view2d_view_ortho``. All material
    layers share that transform and rounded mask. Messages disable animated
    specular so the material does not compete with reading.

    CHAT is the design's own bubble role, so the wrapper hands over no colour:
    the tint lives in the token row and each site only says how opaque its pane
    is. The decision is computed ONCE as `glass_bed`, at the top of the content
    renderer, because the shared bed helper also paints the agent's prose (no
    bed at all), the todo / action containers (a deliberate colour each) and an
    error card (its red) — a style-carried flag would ride into every one of
    those through ``ChatBubbleStyle x = layout.style;``.
    """

    def _pane(self) -> str:
        return _code(_fn_body(CHAT_PRIMITIVES, "void chat_ui_draw_glass_pane("))

    def _bubble(self) -> str:
        return _code(_fn_body(CHAT_WIDGETS, "float chat_ui_draw_bubble("))

    def test_the_chat_pane_is_one_delegating_draw(self) -> None:
        """A wrapper that drew its own roundbox would be a second material,
        free to disagree with the role table."""
        body = self._pane()
        assert body.count("mixar_glass_draw(") == 1, "the wrapper does not draw exactly one pane"
        for forbidden in ("draw_roundbox_4fv", "mixar_glass_tokens", "draw_roundbox_corner_set"):
            assert forbidden not in body, f"the wrapper reaches for {forbidden}"

    def test_the_chat_pane_takes_the_chat_role_and_no_other(self) -> None:
        body = self._pane()
        assert "style.role = ui::MIXAR_GLASS_CHAT;" in body
        assert set(re.findall(r"\bMIXAR_GLASS_[A-Z]+\b", body)) == {"MIXAR_GLASS_CHAT"}

    def test_the_chat_pane_turns_the_streak_off(self) -> None:
        """Messages keep their material still while the user reads."""
        assert "style.draw_specular = false;" in self._pane()

    def test_the_chat_pane_hands_over_no_colour(self) -> None:
        """The tint is the CHAT row's; a site that passed one lets each bubble
        pick its own material, which is the drift the role table prevents."""
        body = self._pane()
        assert "bg_color" not in body, "the wrapper reads a colour"
        touched = set(re.findall(r"style\.([A-Za-z_][A-Za-z0-9_]*)", body))
        assert touched == {"role", "radius", "alpha", "draw_specular"}, (
            f"the wrapper touches {sorted(touched)}; only role / radius / alpha / draw_specular"
        )

    def test_the_bed_branch_is_an_argument_not_a_style_field(self) -> None:
        """`glass` is an explicit parameter (defaulted flat), so the block
        containers that reuse this helper are flat by construction and no
        derived style can carry the flag into them."""
        bubble = self._bubble()
        assert "if (glass) {" in bubble
        assert (
            "chat_ui_draw_glass_pane(&bubble_rect, style->corner_radius, style->bg_color[3]);"
            in bubble
        )
        assert "chat_ui_draw_rounded_rect(&bubble_rect, style->corner_radius, style->bg_color);" in bubble
        assert "bool glass = false);" in _code(CHAT_INTERN), "the parameter is not defaulted flat"
        assert "is_glass" not in bubble
        assert "is_glass" not in _code(CHAT_INTERN)

    def test_the_user_message_is_the_only_glass_bed(self) -> None:
        """An error card keeps its red and the agent's prose has no bed — only
        the user's own message is the chat's one real card."""
        assert (
            "const bool glass_bed = layout.is_user && !layout.is_error;" in _code(CHAT_CONTENT)
        )

    def test_every_content_bed_shares_the_one_decision(self) -> None:
        """Both markdown beds branch on `glass_bed`, and every plain-text call
        passes it; the ephemeral call is the agent's, so it stays flat."""
        content = _code(CHAT_CONTENT)
        assert content.count("if (glass_bed) {") == 2
        assert content.count("chat_ui_draw_glass_pane(&bubble_rect,") == 2
        calls = re.findall(r"chat_ui_draw_bubble\(&layout\.style,[^;]*;", content)
        assert len(calls) == 4, "the four plain-text beds are not all present"
        for call in calls:
            assert call.rstrip().endswith("glass_bed);"), f"a bed ignores glass_bed: {call!r}"
        assert "chat_ui_draw_ephemeral_bubble(&layout.style," in content

    def test_the_content_panes_hand_over_only_the_alpha(self) -> None:
        """`bg_color[3]` is the one thing a site says — how opaque its pane is.
        The RGB comes from the CHAT row and is never read here."""
        calls = re.findall(r"chat_ui_draw_glass_pane\(([^;]*)\);", _code(CHAT_CONTENT))
        assert len(calls) == 2
        for call in calls:
            assert call.strip().endswith("layout.style.bg_color[3]"), (
                f"a call site picks a colour: {call!r}"
            )

    def test_the_block_containers_stay_flat(self) -> None:
        """The todo and action beds derive from the same style but hand over a
        colour on purpose, so they must not be glassed."""
        render = _code(CHAT_RENDER)
        calls = re.findall(r"chat_ui_draw_bubble\(([^;]*)\);", render)
        assert len(calls) == 3, "the block containers changed count"
        for call in calls:
            assert call.rstrip().endswith("layout.content_width"), (
                f"a container grew an argument: {call!r}"
            )

    def test_the_deliberate_container_colours_survive(self) -> None:
        """A blanket conversion of the shared fill would have destroyed the
        danger red, its hover, and the teal hover wash."""
        render = _code(CHAT_RENDER)
        assert "float danger_color[4] = {0.8f, 0.2f, 0.2f, 0.3f};" in render
        assert "float danger_hover[4] = {0.9f, 0.3f, 0.3f, 0.5f};" in render
        assert "memcpy(action_style.bg_color, layout.style.hover_color," in render
        assert "chat_ui_get_prompt_button_color(slot_todo_style.bg_color);" in render


class TestTheIslandCardIsAPane:
    """The island's card bed (`agent_ui_draw.cc`), and the two island slabs
    that must stay flat.

    The island draws in WINDOW-physical pixels: `agent_bubble_island_begin`
    pushes a `-winrct` translate and every rect in `AgentIslandLayout` is in
    that space. Every material layer uses the same transform and silhouette.
    The island and pill disable animated specular by default.

    CARD is the design's own card role: its token row is dark glass with a
    whisper of green, so the wrapper hands over no colour and the island
    adds no second wash. The neon meter is the card's green — putting the
    artboard's saturated ramp on the pane tint read as a plastic header.
    What the role cannot carry is that the artboard's axis is diagonal —
    the kit shades vertically. That trade is deliberate and recorded at
    the call site.
    """

    def _island(self) -> str:
        return _code(_fn_body(AGENT_DRAW, "void agent_ui_draw_island("))

    def _card_call(self) -> list[str]:
        calls = re.findall(r"glass_fill_round\(([^;]*)\);", _code(AGENT_DRAW))
        card = [call for call in calls if "MIXAR_GLASS_CARD" in call]
        assert len(card) == 1, f"the island's card bed is not one call: {card}"
        return [arg.strip() for arg in card[0].split(",")]

    def test_the_card_bed_is_the_card_role_on_the_cards_own_rect(self) -> None:
        """The bed's whole shape in one place — rect, role, radius and the two
        layers switched off. Any of them moving is a re-material."""
        assert self._card_call() == [
            "&layout->card_fill",
            "ui::MIXAR_GLASS_CARD",
            "(AGENT_CARD_RADIUS - AGENT_CARD_BORDER) * u",
            "false",
            "false",
            "!agent_bubble_island_bed_is_transparent()",
        ], f"the card bed changed shape: {self._card_call()}"

    def test_the_pane_reuses_the_meters_inner_edge(self) -> None:
        """`card_fill` is inset by exactly the band's `AGENT_CARD_BORDER`, so
        the pane's radius has to come off the card's by that same amount: at
        the full radius the corner arc crosses the band along the diagonal."""
        layout = _code(AGENT_LAYOUT)
        assert "AGENT_CARD_X + AGENT_CARD_BORDER" in layout
        assert "AGENT_CARD_Y + AGENT_CARD_BORDER" in layout
        assert "AGENT_CARD_BORDER * 2" in layout
        assert "AGENT_CARD_BORDER" in self._card_call()[2], "the radius ignores the band"

    def test_the_island_and_pill_default_to_a_still_material(self) -> None:
        """The shared wrapper requires an explicit opt-in for a moving streak."""
        draw = _code(AGENT_DRAW)
        assert "const bool specular = false" in draw, "the wrapper enabled the streak by default"
        assert "style.draw_specular = specular;" in draw
        assert draw.count("glass_fill_round(&pill, ui::MIXAR_GLASS_PILL, h * 0.5f);") == 2

    def test_the_glass_wrapper_hands_over_no_colour(self) -> None:
        """Same contract as the chat's wrapper: role and radius, plus the two
        layer switches — nothing that could pick a tint."""
        body = _fn_body(AGENT_DRAW, "void glass_fill_round(")
        touched = set(re.findall(r"style\.([A-Za-z_][A-Za-z0-9_]*)", body))
        assert touched == {"role", "radius", "draw_shadow", "draw_specular", "draw_tint"}, (
            f"the wrapper touches {sorted(touched)}"
        )

    def test_the_meter_paints_its_band_and_not_the_whole_card(self) -> None:
        """The meter used to fill the whole card rect and lean on an opaque
        gradient painted afterwards to hide its middle. Over a translucent bed
        that middle shows, so the ring itself is drawn as a band."""
        body = _code(_fn_body(AGENT_DRAW, "void draw_card_border_meter("))
        assert body.count("draw_roundbox_4fv_ex(") == 1
        assert "nullptr, nullptr, 1.0f, band, width, radius" in body
        assert "fill_round(rect," not in body, "the meter still floods the card"
        assert body.count("fill_round(&seg, width * 0.5f, lit)") == 1, "the lit runs are gone"
        assert body.index("draw_roundbox_4fv_ex(") < body.index("if (unknown) {"), (
            "the unknown case returns before the band is drawn"
        )

    def test_the_meter_is_laid_under_the_bed(self) -> None:
        """Draw order is what closes the abutment: the pane has to fill the
        ring's interior to exactly its inner edge, so it comes second."""
        island = self._island()
        assert island.index("draw_card_border_meter(") < island.index(
            "glass_fill_round(&layout->card_fill"
        ), "the bed is drawn before the meter it abuts"

    def test_the_cards_middle_carries_the_green_alone(self) -> None:
        """The CARD row IS the bed, so a wash over it would double the
        material — the opposite of the viewport panel, whose near-black
        bed keeps its call-site wash. One draw touches the bed."""
        assert self._island().count("layout->card_fill") == 1

    def test_the_strip_and_the_inner_panel_stay_flat(self) -> None:
        """The strip sits under tab pills and the panel under the category
        panes' own opaque washes, so a pane beneath either is paid for and
        never seen."""
        strip = _code(_fn_body(AGENT_DRAW, "void draw_tab_strip("))
        assert "fill_round(&layout->strip, AGENT_STRIP_RADIUS * u, surface);" in strip
        assert "if (!agent_bubble_island_bed_is_transparent())" in strip
        island = self._island()
        assert "fill_round(&layout->panel, AGENT_PANEL_RADIUS * u, surface);" in island
        assert "if (!agent_bubble_island_bed_is_transparent())" in island
        assert "glass_fill_round(&layout->panel" not in island
        assert "glass_fill_round(&layout->strip" not in _code(AGENT_DRAW)

    def test_the_dead_diagonal_axis_is_gone(self) -> None:
        """Nothing samples the artboard's diagonal axis now that the bed is a
        pane, so it must not survive as layout state or as tokens — an axis
        nobody reads is exactly the drift the register exists to catch."""
        for src in (AGENT_DRAW, AGENT_LAYOUT, AGENT_LAYOUT_HH, AGENT_THEME):
            assert "card_grad" not in src, "the diagonal axis is still declared"
            assert "AGENT_CARD_GRAD_" not in src
            assert "AGENT_COL_CARD_" not in src
        assert "fill_round_gradient(&layout->card_fill" not in _code(AGENT_DRAW)


class TestZenChromeUsesTheFamily:
    """Zen mode chrome is the same kit on macOS and Windows.

    The island/pill frost through GHOST. Cinema cards float over the
    viewport, and the Zen topbar / View3D header used to be theme slabs.
    Both now take a family pane so the workspace reads as one material.
    Rows, tracks and chips stay flat — a pane there is a groove that
    vanished.
    """

    def test_cinema_cards_are_the_card_pane(self) -> None:
        paint = (ED / "space_view3d" / "view3d_director_cinema_paint.cc").read_text(
            encoding="utf-8"
        )
        body = _fn_body(paint, "void cinema_glass_panel(")
        assert "style.role = ui::MIXAR_GLASS_CARD;" in body
        assert "mixar_glass_draw(pane, style);" in body
        assert "style.draw_specular = false;" in body
        left = (ED / "space_view3d" / "view3d_director_cinema_left.cc").read_text(
            encoding="utf-8"
        )
        right = (ED / "space_view3d" / "view3d_director_cinema_right.cc").read_text(
            encoding="utf-8"
        )
        dock = (ED / "space_view3d" / "view3d_director_cinema_dock.cc").read_text(
            encoding="utf-8"
        )
        minimap = (ED / "space_view3d" / "view3d_director_minimap_draw.cc").read_text(
            encoding="utf-8"
        )
        assert left.count("cinema_glass_panel(card") == 3
        assert "cinema_glass_panel(cameras," in right
        assert "cinema_glass_panel(panel," in dock
        assert "cinema_glass_panel(card," in minimap
        assert "cinema_panel(row," in left
        assert "cinema_panel(track," in right

    def test_zen_header_is_the_island_pane(self) -> None:
        chrome = (IFACE / "interface_mixar_zen_chrome.cc").read_text(encoding="utf-8")
        assert 'STREQ(workspace->id.name + 2, "Zen Mode")' in chrome
        assert "style.role = MIXAR_GLASS_ISLAND;" in chrome
        assert "GPU_clear_color(0.040f, 0.055f, 0.048f, 1.0f)" in chrome
        assert "mixar_glass_draw(pane, style);" in chrome
        area = (ED / "screen" / "area.cc").read_text(encoding="utf-8")
        assert "mixar_zen_header_clear(C, region)" in area
        cmake = (IFACE / "CMakeLists.txt").read_text(encoding="utf-8")
        assert "interface_mixar_zen_chrome.cc" in cmake

