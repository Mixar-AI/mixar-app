# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Cross-language contracts for the model picker and owning settings overlay."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = (ROOT / 'src/source/blender/editors/space_mixie/mixie_draw_moodboard_node_settings.cc').read_text()


def test_default_card_keeps_model_direct_and_parameters_in_overlay():
    assert '"model",' in SOURCE and 'ui::ButtonType::Menu' in SOURCE
    assert 'button_operator_ptr_ensure(button), "node_id", node_id' in SOURCE
    assert 'ICON_PREFERENCES' in SOURCE
    assert 'RNA_collection_begin' not in SOURCE
    assert 'value_integer' not in SOURCE
    assert 'Settings are locked while generating' in SOURCE


def test_overlay_native_dismissal_is_scoped_to_settings_operator():
    wm = (ROOT / 'src/source/blender/windowmanager/intern/wm_operators.cc').read_text()
    assert 'STREQ(op->idname, "MIXIE_OT_moodboard_node_settings")' in wm
    assert 'RNA_int_get_array(op->ptr, "overlay_offset", offset)' in wm
    assert 'dialog_exec_cb(&ctx, data, block)' in wm
    assert 'block_bounds_set_popup(block, 6 * UI_SCALE_FAC, offset)' in wm


def test_local_assemble_has_no_model_selector():
    from mixar.modules.moodboard.core.node_action_types import ACTION_TYPES
    assert ACTION_TYPES[11][0] == 'ASSEMBLE'
    assemble = SOURCE.split('if (action == 11)')[1].split('char model')[0]
    assert '"Attachment settings"' in assemble
    assert 'return;' in assemble and '"model"' not in assemble
