# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Library navigation must not fall through to chat or strand filtered results."""
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from mixar.modules.agent_bubble.ui.properties import generations_props

ROOT = Path(__file__).resolve().parents[1]
CPP = ROOT / 'src/source/blender/editors/space_agent_bubble'
PY_ROOT = ROOT / 'src/scripts/mixar/modules/agent_bubble'


def test_filter_reset_keeps_selection_and_sidebar_position():
    state = SimpleNamespace(mixar_generations_scroll=.75,
                            mixar_generations_library_scroll=.6,
                            mixar_generations_selected='asset:kept')
    area = SimpleNamespace(type='AGENT_BUBBLE', tag_redraw=MagicMock())
    context = SimpleNamespace(window_manager=SimpleNamespace(windows=[
        SimpleNamespace(screen=SimpleNamespace(areas=[area]))]))
    generations_props._reset_scroll(state, context)
    assert state.mixar_generations_scroll == 0
    assert state.mixar_generations_library_scroll == .6
    assert state.mixar_generations_selected == 'asset:kept'
    area.tag_redraw.assert_called_once()


def test_library_keymap_survives_preset_reload_and_precedes_transcript():
    keymap = (PY_ROOT / 'ui/operators/generations_navigation.py').read_text()
    native = (CPP / 'agent_ui_generations_navigation.cc').read_text()
    space = (CPP / 'space_agent_bubble.cc').read_text()
    assert 'keyconfigs.addon' in keymap
    for event in ('WHEELUPMOUSE', 'WHEELDOWNMOUSE', 'TRACKPADPAN',
                  'PAGE_UP', 'PAGE_DOWN', 'HOME', 'END'):
        assert repr(event) in keymap
    assert 'event->type == MOUSEPAN' in native
    assert 'SPACE_AGENT_BUBBLE' in native and 'RGN_TYPE_WINDOW' in native
    assert '"GENERATIONS"' in native
    init = space[space.index('static void agent_bubble_main_region_init'):]
    assert init.index('"Agent Bubble Library"') < init.index('mixie_chat_main_region_init')


def test_no_asset_or_library_enumeration_cap():
    data = (CPP / 'agent_ui_generations_data.cc').read_text()
    model = (CPP / 'agent_ui_generations_intern.hh').read_text()
    assert 'GEN_MAX_ITEMS' not in data + model
    assert 'std::vector<GenItem> items' in model
    assert 'std::vector<std::string> lib_names' in model


def test_scrolled_buttons_keep_asset_identity_when_hovered():
    native = (CPP / 'agent_ui_generations_navigation.cc').read_text()
    assert 'RNA_string_get(a->opptr, "value") == RNA_string_get(b->opptr, "value")' in native
    for name in ('agent_ui_generations_grid.cc', 'agent_ui_generations_libraries.cc'):
        assert 'button_func_identity_compare_set(but, agent_ui_generations_button_identity)' in (CPP / name).read_text()
