# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Width-driven layout of the Zen menu bar and scene toolbar."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mixar.modules.common.utils import topbar_layout as bar
from mixar.modules.workflow.core import zen_toolbar_layout as tiers
from mixar.modules.workflow.ui.headers import mode_filter_header as header


# -- Scene toolbar tiers ----------------------------------------------------

def test_tiers_follow_lane_budgets_not_fixed_breakpoints():
    # A 1512-logical window (MacBook Pro 14" at 1x) has room for the inline
    # render engine and samples; they must not collapse into a popover.
    assert tiers.tier_for_width(1512) == tiers.FULL
    assert tiers.tier_for_width(tiers.required_width(tiers.FULL) - 1) == tiers.COMPACT


def test_each_tier_is_the_widest_that_fits():
    order = [tiers.FULL, tiers.COMPACT, tiers.NARROW, tiers.TIGHT]
    needs = [tiers.required_width(t) for t in order]
    assert needs == sorted(needs, reverse=True)
    for tier, need in zip(order, needs):
        assert tiers.tier_for_width(need) == tier
    assert tiers.tier_for_width(needs[-1] - 1) == tiers.MINIMAL
    assert tiers.tier_for_width(0) == tiers.MINIMAL


def test_overflow_keeps_every_control_reachable():
    assert tiers.overflow_sections(tiers.FULL) == ()
    assert tiers.overflow_sections(tiers.COMPACT) == ()
    assert tiers.overflow_sections(tiers.NARROW) == ("PLAYBACK", "SKY", "EXPORT")
    assert tiers.overflow_sections(tiers.TIGHT)[0] == "CINEMA"
    assert set(tiers.overflow_sections(tiers.MINIMAL)) == {
        "CINEMA", "GUIDES", "PLAYBACK", "SKY", "EXPORT"}


# -- Menu bar lanes ---------------------------------------------------------

def test_menus_collapse_only_when_they_reach_the_slider():
    assert not bar.collapse_editor_menus(1512)
    assert not bar.collapse_editor_menus(800)
    assert bar.collapse_editor_menus(700)
    # Engine's Workspaces icon follows the menus, so it collapses sooner.
    width = 2 * (bar.EDITOR_MENUS_PX + bar.SLIDER_HALF_UNITS * bar.UNIT_PX
                 + bar.SLIDER_CLEARANCE_PX) + 10
    assert not bar.collapse_editor_menus(width)
    assert bar.collapse_editor_menus(width, engine=True)


@pytest.mark.parametrize("width", [3000, 1512, 1024, 900, 800, 700, 600, 400])
@pytest.mark.parametrize("engine", [False, True])
@pytest.mark.parametrize("email", ["rahul@mixar.app",
                                   "someone.with.a.very.long.name@example-company.com"])
def test_profile_pill_stays_inside_its_lane(width, engine, email):
    units, label = bar.profile_pill(email, width, engine=engine)
    lane = bar.side_lane_px(width) - bar.RIGHT_FIXED_PX
    if engine:
        lane -= bar.ENGINE_RIGHT_EXTRA_PX
    if label:
        assert units * bar.UNIT_PX <= lane
        assert len(label) <= len(email)
        if label != email:
            assert bar.ELLIPSIS in label and label.endswith(email[-3:])
    else:
        assert units == bar.PROFILE_AVATAR_UNITS


def test_profile_pill_keeps_full_email_when_it_fits():
    email = "rahul@mixar.app"
    assert bar.profile_pill(email, 1512) == (len(email) * 0.35 + 3.8, email)


def test_truncate_middle():
    assert bar.truncate_middle("abcdef", 10) == "abcdef"
    assert bar.truncate_middle("abcdefghij", 5) == "ab…ij"
    assert bar.truncate_middle("abc", 1) == "…"
    assert bar.truncate_middle("abc", 0) == ""


@pytest.mark.parametrize("width,collapsed", [(1512, False), (600, True)])
def test_zen_header_collapses_menus_on_narrow_windows(monkeypatch, width, collapsed):
    editor_menus = MagicMock()
    types = SimpleNamespace(TOPBAR_MT_editor_menus=editor_menus,
                            MIXAR_MT_editor_menus_collapsed=object())
    monkeypatch.setattr(header.bpy, "types", types)
    monkeypatch.setattr(header, "_draw_mode_slider", MagicMock())
    layout = MagicMock()
    context = SimpleNamespace(
        window=object(), screen=SimpleNamespace(show_fullscreen=False),
        workspace=SimpleNamespace(name="Zen Mode"),
        area=SimpleNamespace(width=width * 2),
        preferences=SimpleNamespace(system=SimpleNamespace(ui_scale=2.0)),
    )

    header._patched_draw_left(SimpleNamespace(layout=layout), context)

    if collapsed:
        layout.menu.assert_called_once_with(
            "MIXAR_MT_editor_menus_collapsed", text="", icon="MIXAR_ICON")
        editor_menus.draw_collapsible.assert_not_called()
    else:
        editor_menus.draw_collapsible.assert_called_once_with(context, layout)
        layout.menu.assert_not_called()


def test_object_controls_button_counts_against_the_left_lane():
    for tier in (tiers.FULL, tiers.COMPACT, tiers.NARROW, tiers.TIGHT):
        assert (tiers.required_width(tier, object_controls=True)
                > tiers.required_width(tier))
    width = tiers.required_width(tiers.FULL)
    assert tiers.tier_for_width(width) == tiers.FULL
    assert tiers.tier_for_width(width, object_controls=True) == tiers.COMPACT


@pytest.mark.parametrize("engine", [False, True])
def test_login_turns_icon_only_before_reaching_the_slider(engine):
    assert bar.login_button(1512) == (bar.LOGIN_UNITS, "Login")
    for width in (3000, 1512, 1024, 900, 760, 640, 560, 400):
        units, label = bar.login_button(width, engine=engine)
        lane = bar.side_lane_px(width) - bar.RIGHT_FIXED_PX
        if engine:
            lane -= bar.ENGINE_RIGHT_EXTRA_PX
        if label:
            assert units * bar.UNIT_PX <= lane
        else:
            assert units == bar.LOGIN_ICON_UNITS
    assert bar.login_button(560, engine=engine)[1] == ""


@pytest.mark.parametrize("logged_in", [False, True])
def test_sound_toggle_gives_way_only_when_the_account_cannot_fit(logged_in):
    assert bar.show_sound_toggle(1512, logged_in=logged_in)
    assert bar.show_sound_toggle(560, logged_in=logged_in)
    # 560 px at 125% UI scale.
    assert not bar.show_sound_toggle(448, logged_in=logged_in)
    units, _ = (bar.profile_pill("a@b.co", 448, sound=False) if logged_in
                else bar.login_button(448, sound=False))
    lane = bar.side_lane_px(448) - bar.RIGHT_FIXED_PX + bar.SOUND_TOGGLE_PX
    assert units * bar.UNIT_PX <= lane


def test_engine_keeps_full_selectors_only_beside_a_whole_account_label():
    short = bar.full_account_units(True, "rahul@mixar.app")
    long = bar.full_account_units(True, "someone.with.a.long.name@example-company.com")
    assert not bar.engine_full_selectors(1600, short)
    assert bar.engine_full_selectors(2400, long)
    assert not bar.engine_full_selectors(1800, long)
    for width in (1640, 1800, 2000, 2400):
        for units in (short, long, bar.LOGIN_UNITS):
            if bar.engine_full_selectors(width, units):
                email = "x" * int(round((units - bar.PROFILE_BASE_UNITS) / bar.PROFILE_CHAR_UNITS))
                assert bar.profile_pill(email, width, engine=True, selectors=True)[1] == email
