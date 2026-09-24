# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""The restored X shares layout, draw, input and QA on every active card."""
from pathlib import Path

SPACE = Path(__file__).resolve().parents[2] / 'src/source/blender/editors/space_view3d'


def test_active_cards_reserve_and_draw_the_action_slot():
    cards = (SPACE / 'view3d_agent_panel_layout.cc').read_text()
    layout = cards[cards.index('/* The two glyph buttons'):cards.index('rcti *eye')]
    assert 'action->xmax = rect->xmax - icon_inset' in layout
    assert 'action->xmin = action->xmax - icon + 1' in layout
    assert 'if (' not in layout
    draw = (SPACE / 'view3d_agent_panel_draw.cc').read_text()
    assert 'default:\n      ED_agent_panel_draw_close(card.action_rect, alpha, hover == AgentPanelHit::Action);' in draw
    close = draw[draw.index('void ED_agent_panel_draw_close('):]
    assert 'view3d_agent_panel_glyph_cross(glyph, UI_SCALE_FAC, color)' in close
    assert 'card.has_workspace ? card.eye_rect.xmin : card.action_rect.xmin' in draw


def test_action_target_and_click_keep_the_original_dismiss_contract():
    qa = (SPACE / 'view3d_agent_panel_qa.cc').read_text()
    assert 'agent_panel_card_has_outcome' not in qa
    assert 'agent_panel_dismiss' in qa
    cards = (SPACE / 'view3d_agent_panel_layout.cc').read_text()
    assert 'BLI_rcti_isect_pt(&card.action_rect, mval[0], mval[1])' in cards
    ops = (SPACE / 'view3d_agent_panel_ops.cc').read_text()
    action = ops[ops.index('case AgentPanelHit::Action:'):ops.index('case AgentPanelHit::Card:')]
    assert 'MIXAR_OT_agent_panel_dismiss_card' in action
    assert 'runtime->cards[card_index].task_id' in action
