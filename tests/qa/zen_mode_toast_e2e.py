#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Local Zen/Engine roundtrip and notification fade; no submissions.

QA_HARNESS=/path/to/harness QA_SCENARIO_OUT=/tmp/zen-mode-toast \
    python3 tests/qa/zen_mode_toast_e2e.py
Overlay capture proves appearance, not display cadence.
"""

import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from compact_agent_bubble_e2e import _hover_off, _hover_on
from zen_motion_capture import hover


def _run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-mode-toast'))
    out.mkdir(parents=True, exist_ok=True)
    qa.step('ready', qa.cmd, 'wait_login', timeout=60)
    zen = {'area_type': 'TOPBAR', 'text': 'Zen'}
    engine = {'area_type': 'TOPBAR', 'text': 'Engine'}
    cinema = {'area_type': 'TOPBAR', 'op': 'MIXAR_OT_director_enter'}
    results = {}
    qa.eval('bpy.ops.mixar.bubble_minimise(); result=True')
    qa.click(**zen)
    qa.wait("drv.main_window().workspace.name == 'Zen Mode'", timeout=15)
    qa.eval('def settle():\n    yield 1.2\n    return True\nresult=settle()')
    results['selector-hover'] = qa.step('selector_hover_reverse_idle', hover, qa,
                                       zen, cinema, out/'selector-hover')
    try:
        for target, workspace, selected in ((engine, 'Layout', 0), (zen, 'Zen Mode', 1)):
            qa.step('switch_'+workspace, qa.click, **target)
            qa.wait(f'drv.main_window().workspace.name == {workspace!r}', timeout=15)
            state = qa.eval(f'''
def settled():
    yield 1.2
    target = drv.find_one(**{zen!r})
    win = target['_win']
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(filepath={str(out/(workspace+'.png'))!r})
    return target['mixar_motion']
result=settled()
''')
            assert state['selected'] == selected, state
            results[workspace] = state
    finally:
        if qa.eval("result=drv.main_window().workspace.name != 'Zen Mode'"):
            qa.click(**zen)

    results['toast'] = qa.step('toast_fade_and_retirement', qa.eval, f'''
def observe():
    import time
    from mixar.modules.common.notifications.store import get_notification_store
    from mixar.modules.common.notifications import toast_timer, toast_renderer
    store = get_notification_store()
    # This scenario owns an isolated QA app, so old local fixture notices can expire.
    store.reset()
    store.push('success', 'Motion complete', 'A calm finish, ready for the next task.',
               ttl_ms=1000, id='qa-zen-motion-toast')
    yield .3
    item = next(item for item in store.get_visible() if item.id == 'qa-zen-motion-toast')
    win = drv.main_window()
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(filepath={str(out/'toast-visible.png')!r})
    values = []
    while item.remaining_ms > 0:
        values.append({{'age_ms': item.age_ms, 'opacity': item.opacity}})
        yield .02
    yield .4
    with bpy.context.temp_override(window=win):
        assert win.mixar_qa_capture_frame(filepath={str(out/'toast-retired.png')!r})
    return {{'samples': values, 'retired': not store.contains(item.id),
             'timer_stopped': not bpy.app.timers.is_registered(toast_timer._toast_tick),
             'handler_removed': toast_renderer._draw_handle['handler'] is None}}
result=observe()
''')
    toast = results['toast']
    opacity = [frame['opacity'] for frame in toast['samples']]
    assert sum(0 < value < 1 for value in opacity) >= 4, opacity
    assert all(a >= b for a, b in zip(opacity, opacity[1:])), opacity
    assert toast['retired'] and toast['timer_stopped'] and toast['handler_removed'], toast
    results['paid_requests'] = 0
    results['limits'] = ['Workspace layouts change immediately; no whole-window crossfade.',
                         'Toast samples verify production opacity and retirement, not display vsync.']
    (out/'verdict.json').write_text(json.dumps(results, indent=2)+'\n')
    return results


def run(qa):
    _hover_off(qa)
    try:
        return _run(qa)
    finally:
        _hover_on(qa)


if __name__ == '__main__':
    run_scenario('zen_mode_toast_e2e', run)
