# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Native lifetime contracts backing the live checkpoint/recovery crash replay."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / 'src'
BUBBLE = ROOT / 'source/blender/editors/space_agent_bubble'


def test_every_native_disposal_retires_cocoa_text_input_before_gpu_and_view_free():
    source = (ROOT / 'source/blender/windowmanager/intern/wm_window.cc').read_text()
    body = source.split('static void wm_ghostwindow_destroy(', 1)[1].split('\n}\n', 1)[0]
    assert body.index('Mixar_WindowPrepareForClose(ghost_window)') < body.index('GPU_context_discard(')
    assert body.index('GPU_context_discard(') < body.index('g_system->disposeWindow(')
    cocoa = (ROOT / 'intern/ghost/intern/GHOST_MixarWindowCocoa.mm').read_text()
    # The Metal text client is below the glass wrapper; contentView is wrong.
    assert 'window.firstResponder' in cocoa
    assert 'window.contentView' not in cocoa
    assert cocoa.index('[input deactivate]') < cocoa.index('[window makeFirstResponder:nil]')
    assert cocoa.index('[window makeFirstResponder:nil]') < cocoa.index('[host makeKeyWindow]')
    assert 'Mixar_WindowClearCloseObservers(window)' in cocoa


def test_detached_key_window_is_ordered_out_before_input_context_release():
    cocoa = (ROOT / 'intern/ghost/intern/GHOST_MixarWindowCocoa.mm').read_text()
    fallback = cocoa.split('[host makeKeyWindow];', 1)[1]
    assert '[window resignKeyWindow]' not in cocoa
    assert fallback.index('[window orderOut:nil]') < fallback.index('[input release]')


def test_both_motion_allocators_mark_the_data_as_runtime_only():
    source = (BUBBLE / 'agent_ui_motion.cc').read_text()
    allocations = source.split('region->regiondata = MEM_new<AgentIslandMotion>')
    assert len(allocations) == 3  # Cat and controls can each allocate first.
    for before in allocations[:-1]:
        assert 'region->flag |= RGN_FLAG_TEMP_REGIONDATA;' in before[-100:]


def test_legacy_read_clears_active_and_inactive_regions_without_freeing_foreign_pointers():
    source = (BUBBLE / 'agent_ui_motion.cc').read_text()
    body = source.split('void agent_ui_motion_blend_read_after_liblink(', 1)[1]
    assert '&sl->regionbase' in body
    assert 'area.spacedata.first == sl' in body
    assert '&area.regionbase' in body
    assert 'region.regiondata = nullptr' in body
    assert 'MEM_delete' not in body
    registration = (BUBBLE / 'space_agent_bubble.cc').read_text()
    assert 'st->blend_read_after_liblink = agent_ui_motion_blend_read_after_liblink;' in registration


def test_close_removes_parent_observers_and_modal_retention():
    source = (ROOT / 'intern/ghost/intern/GHOST_SystemCocoa.mm').read_text()
    body = source.split('void Mixar_WindowClearCloseObservers(', 1)[1].split('\n}', 1)[0]
    assert 'mixar_clear_parent_observers_for_child(window)' in body
    assert '[s_mixar_suppressed_floating_docks removeObject:window]' in body
