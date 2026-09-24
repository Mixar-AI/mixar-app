# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Chat click handlers must never touch their region after calling an operator.

An operator called from a region-level handler can close the window that owns
the region (the Agent Bubble purge ran from save_pre while a turn checkpoint was
taken), and the purge restores a live context window, so only a screen walk can
prove the region still exists. Pinned at source level because the dispatchers are
plain C++ with no test seam.
"""
import re
from pathlib import Path

CHAT = Path(__file__).resolve().parents[1] / 'src/source/blender/editors/space_mixie_chat'


def test_no_region_redraw_follows_a_raw_operator_call():
    offenders = []
    for path in sorted(CHAT.glob('*.cc')):
        lines = path.read_text().splitlines()
        for index, line in enumerate(lines):
            if 'WM_operator_name_call_ptr(' not in line and 'WM_operator_name_call(' not in line:
                continue
            window = '\n'.join(lines[index:index + 8])
            if 'ED_region_tag_redraw(region)' in window and 'mixie_chat_region_is_alive' not in window:
                offenders.append(f'{path.name}:{index + 1}')
    assert offenders == [], offenders


def test_dispatchers_use_the_guarded_helper():
    source = (CHAT / 'mixie_chat_hit_testing.cc').read_text()
    assert 'bool mixie_chat_region_is_alive(const bContext *C, const ARegion *region)' in source
    helper = source[source.index('void mixie_chat_call_operator_and_redraw'):]
    helper = helper[:helper.index('\n}\n')]
    assert helper.index('ED_region_tag_redraw(region)') < helper.index('WM_operator_name_call_ptr(')
    assert re.search(r'if \(mixie_chat_region_is_alive\(C, region\)\) \{\s*ED_region_tag_redraw\(region\);', helper)
    # Guard each dispatch surface, independent of local pointer names and
    # consolidation of several buttons into one shared dispatcher.
    for filename in ('mixie_chat_hit_testing.cc', 'mixie_chat_feedback.cc',
                     'mixie_chat_main_region.cc', 'mixie_chat_history_util.cc',
                     'mixie_chat_rules_util.cc'):
        assert re.search(r'mixie_chat_call_operator_and_redraw\(C, region, ot, &\w+\);',
                         (CHAT / filename).read_text()), filename
    assert 'mixie_chat_call_operator_and_redraw(' in (CHAT / 'mixie_chat_intern.hh').read_text()


def test_region_liveness_walks_every_window_and_global_area():
    source = (CHAT / 'mixie_chat_hit_testing.cc').read_text()
    body = source[source.index('bool mixie_chat_region_is_alive'):source.index('void mixie_chat_call_operator_and_redraw')]
    assert 'for (const wmWindow &win : wm->windows)' in body
    assert 'ED_screen_areas_iter (&win, screen, area)' in body  # includes global areas
    assert 'for (const ARegion &candidate : area->regionbase)' in body
