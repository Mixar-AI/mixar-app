# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

from .surface_contracts import (
    AGENT_CONTROLS,
    AGENT_DRAW,
    AGENT_LAYOUT,
    AGENT_LAYOUT_HH,
    AGENT_THEME,
    CHAT_CONTENT,
    CHAT_INTERN,
    CHAT_PRIMITIVES,
    CHAT_RENDER,
    CHAT_WIDGETS,
    ED,
    IFACE,
    _code,
    _fn_body,
    re,
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

    The expanded chat uses PILL's neutral material. Its credit meter renders
    the same white rim, so the pane suppresses its own duplicate rim.
    """

    def _island(self) -> str:
        return _code(_fn_body(AGENT_DRAW, "void agent_ui_draw_island("))

    def _card_call(self) -> list[str]:
        calls = re.findall(r"glass_fill_round\(([^;]*)\);", _code(AGENT_DRAW))
        card = [call for call in calls if "&layout->card_fill" in call]
        assert len(card) == 1, f"the island's card bed is not one call: {card}"
        return [arg.strip() for arg in card[0].split(",")]

    def test_the_card_bed_uses_the_pill_material_on_its_own_rect(self) -> None:
        """The bed's whole shape in one place — rect, role, radius and the two
        layers switched off. Any of them moving is a re-material."""
        assert self._card_call() == [
            "&layout->card_fill",
            "ui::MIXAR_GLASS_PILL",
            "(AGENT_CARD_RADIUS - AGENT_CARD_BORDER) * u",
            "false",
            "false",
            "!agent_bubble_island_bed_is_transparent()",
            "false",
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
        assert touched == {"role", "radius", "draw_shadow", "draw_specular", "draw_tint", "draw_rim"}, (
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

    def test_the_cards_middle_has_one_material(self) -> None:
        """Only one material draw touches the card bed."""
        assert self._island().count("layout->card_fill") == 1

    def test_the_strip_and_the_inner_panel_stay_flat(self) -> None:
        """The strip sits under tab pills and the panel under the category
        panes' own opaque washes, so a pane beneath either is paid for and
        never seen."""
        strip = _code(_fn_body(AGENT_CONTROLS, "void agent_ui_draw_tab_strip("))
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
