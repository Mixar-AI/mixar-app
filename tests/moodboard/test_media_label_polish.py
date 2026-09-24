# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Media and node titles share fixed screen typography and native actions."""

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SPACE = ROOT / 'src/source/blender/editors/space_mixie'


def test_media_names_use_the_same_title_painter_as_generation_nodes():
    labels = (SPACE / 'mixie_draw_moodboard_media_labels.cc').read_text()
    chrome = (SPACE / 'mixie_draw_moodboard_graph_chrome.cc').read_text()
    assert 'image->id.name + 2' in labels
    assert 'moodboard_draw_card_title(' in labels
    assert 'moodboard_draw_card_title(title, rect, selected' in chrome
    assert 'MixarTextRole::Caption, UI_SCALE_FAC' in chrome
    assert 'view2d_scale_get_x' not in labels
    assert 'font_px *=' not in labels


def test_long_titles_fit_without_changing_font_size_or_anchor():
    chrome = (SPACE / 'mixie_draw_moodboard_graph_chrome.cc').read_text()
    assert 'mixar_fit_text(text, max_width, style)' in chrome
    assert 'card.xmin + metrics.padding' in chrome
    assert 'card.xmax - metrics.padding - reserved_width' in chrome
    labels = (SPACE / 'mixie_draw_moodboard_media_labels.cc').read_text()
    assert 'std::clamp' not in labels
    assert 'moodboard_draw_floating_background' not in labels


def test_media_actions_use_toolbar_components_and_screen_space_culling():
    actions = (SPACE / 'mixie_draw_moodboard_media_actions.cc').read_text()
    for button in ('save', 'preview', 'rename'):
        assert (f'{button}, ui::MixarComponent::Action, ui::MixarVariant::Secondary'
                in actions)
    assert 'moodboard_media_action_row_rect(media_pixels, &row_rect)' in actions
    assert 'moodboard_media_action_row_rect(*media_rect' not in actions
    components = (ROOT / 'src/source/blender/editors/interface/mixar/components.cc').read_text()
    assert 'style.component == MixarComponent::Action && button.icon && button.str.empty()' in components


def test_media_title_capture_uses_the_painted_title_geometry():
    targets = (SPACE / 'mixie_moodboard_qa_targets.cc').read_text()
    assert '"moodboard_media_title"' in targets
    assert 'moodboard_node_title_rect(' in targets
    assert 'media_title ? ed::mixie::moodboard_node_card_actions_width(true)' in targets
    assert '!ed::mixie::moodboard_media_rename_is_active(scene, id)' in targets
