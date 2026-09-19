# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The tour's video card lands where the beat says, inside the host.

Contract: the card is the video plus ``CARD_PAD`` on every side — no
controls band below it; the controls strip sits INSIDE the bottom of the
video, and ``layout_from_card_rect`` rebuilds the same layout from the card
rect alone (the session feeds it the animated rect).

Layout is arithmetic over ``config`` so it runs under the ``bpy``/``gpu``/
``blf`` mocks; text measurement goes through ``card._text_width`` which
falls back to a glyph estimate when ``blf.dimensions`` is a MagicMock.
"""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

import pytest  # noqa: E402

from mixar.modules.onboarding.core.tour import beats, config  # noqa: E402
from mixar.modules.onboarding.core.tour.overlays import card  # noqa: E402

HOST = (0.0, 0.0, 1600.0, 900.0)
PLACEMENTS = (
    beats.PLACE_CENTER, beats.PLACE_TOP_LEFT, beats.PLACE_TOP_RIGHT,
    beats.PLACE_BOTTOM_LEFT, beats.PLACE_BOTTOM_RIGHT, beats.PLACE_BOTTOM_CENTER,
)
EPS = 1e-6


def _inside(inner, outer, margin=0.0):
    return (inner[0] >= outer[0] + margin - EPS and inner[1] >= outer[1] + margin - EPS
            and inner[2] <= outer[2] - margin + EPS and inner[3] <= outer[3] - margin + EPS)


def _center(rect):
    return ((rect[0] + rect[2]) * 0.5, (rect[1] + rect[3]) * 0.5)


def _assert_video_only_card(layout, scale=1.0):
    """No chrome: card == video + pad, controls strip inside the video's bottom."""
    pad = config.CARD_PAD * scale
    assert layout.card[0] == pytest.approx(layout.video[0] - pad)
    assert layout.card[1] == pytest.approx(layout.video[1] - pad)
    assert layout.card[2] == pytest.approx(layout.video[2] + pad)
    assert layout.card[3] == pytest.approx(layout.video[3] + pad)
    assert _inside(layout.controls, layout.video)
    assert layout.controls[1] == pytest.approx(layout.video[1])
    assert layout.controls[0] == pytest.approx(layout.video[0])
    assert layout.controls[2] == pytest.approx(layout.video[2])


def test_text_width_is_a_float_under_the_mock():
    w = card._text_width("Pause", 13)
    assert isinstance(w, float) and w > 0.0
    assert card._text_width("", 13) == 0.0


@pytest.mark.parametrize("placement", PLACEMENTS)
@pytest.mark.parametrize("variant", sorted(config.CARD_VARIANTS))
def test_every_placement_lands_inside_host_with_margins(variant, placement):
    layout = card.compute_card_layout(variant, placement, HOST, 1.0)
    assert _inside(layout.card, HOST, config.CARD_MARGIN)
    assert _inside(layout.video, layout.card)
    _assert_video_only_card(layout)
    for rect in layout.buttons.values():
        assert _inside(rect, layout.controls)
    vw = layout.video[2] - layout.video[0]
    vh = layout.video[3] - layout.video[1]
    assert vw == pytest.approx(config.CARD_VARIANTS[variant])
    assert vw / vh == pytest.approx(config.CARD_ASPECT)


def test_placements_pick_the_right_corner():
    m = config.CARD_MARGIN
    tl = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 1.0).card
    tr = card.compute_card_layout("half", beats.PLACE_TOP_RIGHT, HOST, 1.0).card
    bl = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0).card
    br = card.compute_card_layout("half", beats.PLACE_BOTTOM_RIGHT, HOST, 1.0).card
    bc = card.compute_card_layout("half", beats.PLACE_BOTTOM_CENTER, HOST, 1.0).card
    cc = card.compute_card_layout("hero", beats.PLACE_CENTER, HOST, 1.0).card
    assert tl[0] == pytest.approx(m) and tl[3] == pytest.approx(HOST[3] - m)
    assert tr[2] == pytest.approx(HOST[2] - m) and tr[3] == pytest.approx(HOST[3] - m)
    assert bl[0] == pytest.approx(m) and bl[1] == pytest.approx(m)
    assert br[2] == pytest.approx(HOST[2] - m) and br[1] == pytest.approx(m)
    assert bc[1] == pytest.approx(m) and _center(bc)[0] == pytest.approx(800.0)
    assert _center(cc) == pytest.approx(_center(HOST))


def test_ui_scale_scales_the_card():
    big = (0.0, 0.0, 3200.0, 1800.0)
    one = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, big, 1.0)
    two = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, big, 2.0)
    assert (two.video[2] - two.video[0]) == pytest.approx(2 * (one.video[2] - one.video[0]))
    assert (two.controls[3] - two.controls[1]) == pytest.approx(2 * config.CARD_CONTROLS_H)
    assert two.card[0] == pytest.approx(2 * config.CARD_MARGIN)
    _assert_video_only_card(two, scale=2.0)


def test_card_is_only_pad_larger_than_the_video():
    layout = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 1.0)
    assert config.CARD_PAD <= 2
    assert (layout.card[3] - layout.card[1]) == pytest.approx(
        (layout.video[3] - layout.video[1]) + 2 * config.CARD_PAD)
    assert (layout.controls[3] - layout.controls[1]) == pytest.approx(config.CARD_CONTROLS_H)


@pytest.mark.parametrize("placement", PLACEMENTS)
@pytest.mark.parametrize("variant", sorted(config.CARD_VARIANTS))
def test_layout_from_card_rect_reproduces_the_target(variant, placement):
    target = card.compute_card_layout(variant, placement, HOST, 1.5)
    rebuilt = card.layout_from_card_rect(target.card, 1.5)
    assert rebuilt.card == pytest.approx(target.card)
    assert rebuilt.video == pytest.approx(target.video)
    assert rebuilt.controls == pytest.approx(target.controls)
    assert rebuilt.buttons.keys() == target.buttons.keys()
    for name, rect in target.buttons.items():
        assert rebuilt.buttons[name] == pytest.approx(rect)


def test_layout_from_an_intermediate_rect_keeps_buttons_inside_the_strip():
    a = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0).card
    b = card.compute_card_layout("hero", beats.PLACE_CENTER, HOST, 1.0).card
    mid = tuple((x + y) * 0.5 for x, y in zip(a, b))
    layout = card.layout_from_card_rect(mid, 1.0)
    assert layout.card == pytest.approx(mid)
    _assert_video_only_card(layout)
    for rect in layout.buttons.values():
        assert _inside(rect, layout.controls)


def test_video_corners_stay_inside_the_rounded_background():
    # The video quad is square-cornered; the background arc must contain it.
    r, pad = config.CARD_RADIUS, config.CARD_PAD
    assert ((r - pad) ** 2) * 2 <= r * r + 1e-9


def test_margin_gives_way_on_a_short_host():
    # 5% of a 900 px host is 45 px, below the 56 px a 2x margin would want.
    layout = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 2.0)
    assert layout.card[0] == pytest.approx(HOST[3] * 0.05)
    assert _inside(layout.card, HOST)


def test_bottom_left_card_is_lifted_above_an_intersecting_island():
    island = (0.0, 0.0, 700.0, 320.0)
    plain = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0)
    assert plain.card[1] < island[3]  # would overlap without the island
    lifted = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0,
                                      island_rect=island)
    assert lifted.card[1] >= island[3]
    assert _inside(lifted.card, HOST)
    assert lifted.card[0] == plain.card[0]


def test_island_far_away_does_not_move_the_card():
    island = (1200.0, 0.0, 1600.0, 300.0)
    plain = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0)
    same = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0,
                                    island_rect=island)
    assert same.card == plain.card


def test_top_placement_ignores_the_island():
    island = (0.0, 400.0, 900.0, 900.0)
    plain = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 1.0)
    same = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 1.0,
                                    island_rect=island)
    assert same.card == plain.card


@pytest.mark.parametrize("host", [(0.0, 0.0, 400.0, 300.0), (100.0, 50.0, 420.0, 260.0)])
def test_hero_shrinks_to_fit_a_tiny_host_keeping_aspect(host):
    layout = card.compute_card_layout("hero", beats.PLACE_CENTER, host, 1.0)
    assert _inside(layout.card, host)
    vw = layout.video[2] - layout.video[0]
    vh = layout.video[3] - layout.video[1]
    assert vw < config.CARD_VARIANTS["hero"]
    assert vw / vh == pytest.approx(config.CARD_ASPECT)
    assert _inside(layout.video, layout.card)
    assert _inside(layout.controls, layout.card)


def test_hit_test_every_button_and_outside():
    layout = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0)
    for name in ("pause", "speed", "skip", "exit"):
        x, y = _center(layout.buttons[name])
        assert card.hit_test(layout, x, y) == name
    vx, vy = _center(layout.video)
    assert card.hit_test(layout, vx, vy) == "card"
    # The strip between the button groups is still the card (click = pause).
    sx = (layout.buttons["speed"][2] + layout.buttons["skip"][0]) * 0.5
    assert card.hit_test(layout, sx, _center(layout.controls)[1]) == "card"
    assert card.hit_test(layout, HOST[2] - 1.0, HOST[3] - 1.0) is None
    assert card.hit_test(layout, layout.card[0] - 1.0, layout.card[1]) is None


def test_buttons_do_not_overlap():
    layout = card.compute_card_layout("half", beats.PLACE_BOTTOM_RIGHT, HOST, 1.0)
    b = layout.buttons
    assert b["pause"][2] <= b["speed"][0]
    assert b["speed"][2] <= b["skip"][0]
    assert b["skip"][2] <= b["exit"][0]


def test_exit_confirm_is_centred_and_buttons_sit_inside_the_dialog():
    layout = card.compute_exit_confirm_layout(HOST, 1.0)
    assert _center(layout.dialog) == pytest.approx(_center(HOST))
    assert layout.dialog[2] - layout.dialog[0] == pytest.approx(380.0)
    assert layout.dialog[3] - layout.dialog[1] == pytest.approx(150.0)
    for name in ("continue", "exit"):
        assert _inside(layout.buttons[name], layout.dialog)
    assert layout.buttons["continue"][2] <= layout.buttons["exit"][0]
    for name in ("continue", "exit"):
        x, y = _center(layout.buttons[name])
        assert card.hit_test_exit_confirm(layout, x, y) == name
    dx, dy = layout.dialog[0] + 2.0, layout.dialog[3] - 2.0
    assert card.hit_test_exit_confirm(layout, dx, dy) == "dialog"
    assert card.hit_test_exit_confirm(layout, 1.0, 1.0) is None


def test_qa_targets_names_and_rects():
    layout = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0)
    exit_layout = card.compute_exit_confirm_layout(HOST, 1.0)
    targets = card.qa_targets(layout, exit_layout)
    names = [t["name"] for t in targets]
    assert names == ["tour_pause", "tour_speed", "tour_skip", "tour_exit",
                     "tour_confirm_continue", "tour_confirm_exit"]
    by_name = {t["name"]: t["rect"] for t in targets}
    assert by_name["tour_pause"] == [float(v) for v in layout.buttons["pause"]]
    assert by_name["tour_confirm_exit"] == [float(v) for v in exit_layout.buttons["exit"]]
    assert [t["name"] for t in card.qa_targets(layout)] == names[:4]
    assert card.qa_targets(None, exit_layout) == targets[4:]


def test_only_hero_and_half_variants_exist_and_unknown_falls_back_to_half():
    assert set(config.CARD_VARIANTS) == {"hero", "half"}
    assert config.CARD_VARIANTS["hero"] > config.CARD_VARIANTS["half"]
    half = card.compute_card_layout("half", beats.PLACE_TOP_LEFT, HOST, 1.0)
    for unknown in ("card", "", "thumbnail"):
        assert card.compute_card_layout(unknown, beats.PLACE_TOP_LEFT, HOST, 1.0).card \
            == half.card
    # The table never asks for a variant that does not exist.
    for b in beats.MIXAR_INTRO.beats:
        assert b.card_variant in config.CARD_VARIANTS, b.id


def test_caption_under_rect_is_centred_below_the_card():
    layout = card.compute_card_layout("hero", beats.PLACE_CENTER, HOST, 1.0)
    rect = card.caption_under_rect(layout, "Replay any time from Help → Start tour", 1.0)
    assert _center(rect)[0] == pytest.approx(_center(layout.card)[0])
    assert rect[3] == pytest.approx(layout.card[1] - config.CAPTION_UNDER_GAP)
    assert rect[3] - rect[1] == pytest.approx(config.HINT_FONT_PX + 2 * card.CAPTION_PAD_Y)
    assert rect[2] - rect[0] > 2 * card.CAPTION_PAD_X
    two = card.caption_under_rect(layout, "Replay any time from Help → Start tour", 2.0)
    assert two[3] == pytest.approx(layout.card[1] - 2 * config.CAPTION_UNDER_GAP)
    assert (two[3] - two[1]) == pytest.approx(2 * (rect[3] - rect[1]))


def test_draw_caption_under_returns_its_rect_or_none():
    layout = card.compute_card_layout("hero", beats.PLACE_CENTER, HOST, 1.0)
    text = "Replay any time from Help → Start tour"
    assert card.draw_caption_under(layout, text, 1.0, 1.0) == pytest.approx(
        card.caption_under_rect(layout, text, 1.0))
    assert card.draw_caption_under(layout, "", 1.0, 1.0) is None
    assert card.draw_caption_under(layout, text, 1.0, 0.0) is None


def test_draw_card_accepts_the_gate_film_and_never_raises():
    layout = card.compute_card_layout("half", beats.PLACE_BOTTOM_LEFT, HOST, 1.0)
    for film in (0.0, 0.5, 1.0, 7.0, -1.0):
        card.draw_card(layout, None, 0.3, False, 1.0, gate_seconds_left=4.0,
                       caption="Part 1 · The viewport", gate_film=film)
    assert 0.0 < config.GATE_FILM_ALPHA < 0.5


def test_format_rate():
    assert card.format_rate(1.0) == "1×"
    assert card.format_rate(1.25) == "1.25×"
    assert card.format_rate(1.5) == "1.5×"
    assert card.format_rate(2.0) == "2×"
