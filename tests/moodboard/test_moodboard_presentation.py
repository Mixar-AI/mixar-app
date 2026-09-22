# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Cross-editor presentation ownership must survive future UI changes."""
from pathlib import Path

ED = Path(__file__).resolve().parents[2] / 'src/source/blender/editors'


def test_both_hosts_draw_one_canvas_and_chrome():
    drawer = (ED / 'space_view3d/view3d_moodboard_drawer_draw.cc').read_text()
    canvas = (ED / 'space_mixie/mixie_draw_moodboard.cc').read_text()
    assert 'ed::mixie::mixie_moodboard_canvas_draw(C, region)' in drawer
    assert 'mixie_moodboard_chrome_draw(C, region)' in canvas
    assert 'UI_paneltype_draw' not in drawer
    assert 'uiDefBut' not in drawer
    assert 'draw_empty_hint' not in drawer


def test_canvas_cards_and_drawer_share_the_island_palette():
    canvas = (ED / 'space_mixie/mixie_draw_moodboard.cc').read_text()
    card = (ED / 'space_mixie/mixie_draw_moodboard_graph_chrome.cc').read_text()
    drawer = (ED / 'space_view3d/view3d_moodboard_drawer_draw.cc').read_text()
    editor = (ED / 'space_mixie/space_mixie.cc').read_text()
    assert 'moodboard_draw_surface(frame,' in canvas
    assert 'moodboard_draw_surface(rect,' in card
    assert 'ui::mixar_tokens::mixar_zen().panel' in canvas
    assert 'ui::mixar_tokens::mixar_zen().canvas' in drawer
    assert 'ui::mixar_tokens::mixar_zen().canvas' in editor
    assert all('MIXAR_GLASS_MOODBOARD' not in text for text in (canvas, card, drawer))


def test_card_controls_reserve_toolbar_and_template_space():
    layout = (ED / 'space_mixie/mixie_moodboard_node_layout.cc').read_text()
    assert 'moodboard_chrome_metrics(UI_SCALE_FAC)' in layout
    assert 'canvas.xmin +=' in layout and 'canvas.ymax -=' in layout
    assert 'moodboard_node_settings_rect' not in layout
