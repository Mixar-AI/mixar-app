# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""The workflow layout keeps lanes readable and results room to grow."""

import pytest

from mixar.modules.moodboard.core.workflow_layout import (
    CARD_H,
    CARD_W,
    COL_PITCH,
    ROW_PITCH,
    note_height,
    plan_layout,
)


def rects(layout):
    cards = list(layout['ref']) + list(layout['m3d']) + [layout['assemble']]
    if layout['rig'] is not None:
        cards.append(layout['rig'])
    return [(x, y, x + CARD_W, y + CARD_H) for x, y in cards]


def overlaps(a, b):
    return a[0] < b[2] and b[0] < a[2] and a[1] < b[3] and b[1] < a[3]


def test_rows_leave_room_for_a_portrait_result():
    assert ROW_PITCH >= 880.0
    layout = plan_layout(3, True, 400.0)
    tops = [y + CARD_H for _x, y in layout['ref']]
    assert tops[0] - tops[1] == pytest.approx(ROW_PITCH)


def test_body_row_is_on_top_and_stages_run_left_to_right():
    layout = plan_layout(3, True, 400.0)
    assert layout['ref'][0][1] > layout['ref'][1][1] > layout['ref'][2][1]
    assert layout['ref'][0][1] + CARD_H == 0.0
    assert [x for x, _y in layout['m3d']] == [COL_PITCH] * 3
    assert layout['rig'] == (2 * COL_PITCH, layout['ref'][0][1])
    assert layout['assemble'][0] == 3 * COL_PITCH


def test_note_sits_below_the_lanes_without_touching_a_card():
    height = note_height("x" * 1000, 40, 1600.0)
    layout = plan_layout(3, True, height, 1600.0)
    note_x, note_y = layout['note']
    note = (note_x, note_y, note_x + 1600.0, note_y + height)
    assert note[3] < layout['ref'][-1][1]
    assert not any(overlaps(note, card) for card in rects(layout))
    assert layout['bounds'][1] == note_y
    assert layout['bounds'][3] == 0.0
    assert layout['bounds'][2] >= max(card[2] for card in rects(layout))


def test_cards_never_overlap():
    for has_rig in (True, False):
        cards = rects(plan_layout(3, has_rig, 300.0))
        assert not any(overlaps(a, b) for i, a in enumerate(cards) for b in cards[i + 1:])


def test_assemble_is_vertically_centred_on_the_lanes():
    layout = plan_layout(3, True, 300.0)
    centres = [y + CARD_H / 2 for _x, y in layout['ref']]
    assert layout['assemble'][1] + CARD_H / 2 == pytest.approx(sum(centres) / 3)


def test_without_a_rig_assemble_takes_the_rig_column():
    layout = plan_layout(3, False, 300.0)
    assert layout['rig'] is None
    assert layout['assemble'][0] == 2 * COL_PITCH
    assert layout['bounds'][2] == 2 * COL_PITCH + CARD_W


def test_note_height_grows_with_the_text():
    short = note_height("How to use", 40, 1600.0)
    long = note_height("x" * 1000, 40, 1600.0)
    assert short == pytest.approx(1.3 * 40 + 20)
    assert long > short
