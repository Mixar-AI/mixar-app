# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Retiring the standalone editor must preserve the floating agent's ownership."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EDITORS = ROOT / 'src/source/blender/editors'
CHAT = EDITORS / 'space_mixie_chat'


def test_editor_is_unregistered_but_shared_implementation_stays_linked():
    registration = (EDITORS / 'space_api/spacetypes.cc').read_text()
    assert 'ED_spacetype_mixie_chat' not in registration
    rna = (ROOT / 'src/source/blender/makesrna/intern/rna_space.cc').read_text()
    assert '"MIXIE_CHAT"' not in rna and 'RNA_SpaceMixieChat' not in rna
    assert 'RNA_SpaceAgentBubble' in rna
    themes = (ROOT / 'src/source/blender/makesrna/intern/rna_userdef.cc').read_text()
    assert '"MIXIE_CHAT"' not in themes
    assert '"AGENT_BUBBLE"' in themes
    build = (CHAT / 'CMakeLists.txt').read_text()
    for retired in ('space_mixie_chat.cc', 'mixie_chat_header.cc', 'mixie_chat_footer.cc',
                    'mixie_chat_footer_draw.cc', 'mixie_chat_footer_model.cc'):
        assert retired not in build and not (CHAT / retired).exists()
    for shared in ('mixie_chat_ops.cc', 'mixie_chat_main_region.cc', 'mixie_chat_messages.cc',
                   'mixie_chat_ink_events.cc', 'mixie_chat_footer_thumbnails.cc'):
        assert shared in build and (CHAT / shared).exists()


def test_bubble_owns_native_chat_registration_and_addon_keymap():
    bubble = (EDITORS / 'space_agent_bubble/space_agent_bubble.cc').read_text()
    for call in ('mixie_chat_operatortypes();', 'mixie_chat_keymap(keyconf);',
                 'st->dropboxes = mixie_chat_dropboxes;', 'mixie_chat_qa_targets_register();'):
        assert call in bubble
    keymap = (ROOT / 'src/scripts/mixar/modules/space_mixie_chat/ui/keymap.py').read_text()
    assert "name='Agent Chat', space_type='AGENT_BUBBLE'" in keymap
    assert "space_type='MIXIE_CHAT'" not in keymap
    native = (CHAT / 'mixie_chat_ops.cc').read_text()
    assert '"Agent Chat", SPACE_AGENT_BUBBLE, RGN_TYPE_WINDOW' in native
    for action in ('select_text', 'copy', 'paste', 'undo_stamp', 'voice_start', 'ink_flush'):
        assert 'MIXIE_CHAT_OT_' + action in native


def test_profile_login_does_not_depend_on_retired_editor():
    panel = (ROOT / 'src/scripts/mixar/modules/space_mixie_chat/ui/login_panel.py').read_text()
    assert "bl_space_type = 'TOPBAR'" in panel


def test_bubble_free_resets_shared_caches_and_surviving_transcript_can_rebuild():
    bubble = (EDITORS / 'space_agent_bubble/space_agent_bubble.cc').read_text()
    free = bubble.split('static void agent_bubble_free(', 1)[1].split(
        'static void agent_bubble_init(', 1)[0]
    for call in ('mixie_chat_free_runtime(smixie);', 'footer_cache_clear();',
                 'mixie_chat_clear_property_caches();'):
        assert call in free
    messages = (CHAT / 'mixie_chat_messages.cc').read_text()
    heal = messages.split('else if (!g_msg_props.initialized)', 1)[1].split('\n  }', 1)[0]
    assert 'needs_layout_rebuild = true;' in heal


def test_in_place_theme_changes_invalidate_the_shared_footer_cache():
    main = (CHAT / 'mixie_chat_main_region.cc').read_text()
    listener = main.split('void mixie_chat_main_region_listener(', 1)[1].split(
        'void mixie_chat_main_region_layout(', 1)[0]
    window_case = listener.split('case NC_WINDOW:', 1)[1].split('break;', 1)[0]
    assert 'footer_cache_invalidate();' in window_case
