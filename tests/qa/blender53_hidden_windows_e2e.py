#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Free real-window UI observation replay, including the resting island.

Run against an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. No transport, credentials or scene content are changed.
Uses production observation/input functions on timer ticks, never a mocked
dump. macOS/Windows hide the island; Linux collapses a still-drawn window.
Read expanded, pill and main-window PNGs before accepting visual behavior.
"""
import json
import os
from pathlib import Path
import sys

harness = Path(os.environ['QA_HARNESS'])
sys.path[:0] = [str(harness), str(harness / 'scenarios')]
from lib import run_scenario

KEY = 'qa_blender53_hidden_windows'
NS = f"bpy.app.driver_namespace[{KEY!r}]"

APP_CODE = r'''
import base64
import json
import os
from pathlib import Path
import sys
import time
import bpy
from mixar.modules.common.ui_control.core import observe
from mixar.modules.common.ui_control.core import input as native_input
from mixar.modules.common.ui_control.core import ownership
from mixar.modules.common.ui_control.constants import UIError
from mixar.modules.mcp_bridge.core import runtime

assert os.environ.get('MIXAR_QA') == '1'
assert bpy.app.version[:2] == (5, 3)
owner = 'qa-blender53-hidden-windows'
rows = {}
task = None
callback = None
original = None
owned_contexts = []
# The periodic MCP mirror sets native enablement from persisted settings.
# Suspend only that owned-app timer while this QA-only native API probe runs;
# do not enable the connector or persist an MCP preference.
assert not runtime.enabled(), 'replay requires fresh QA app with MCP disabled'
assert not ownership.active(), 'another controller owns input'
assert bpy.context.window_manager.mixar_ui_pending() == 0
ownership_before = {name: getattr(ownership, name) for name in
                    ('_owner', '_generation', '_scene', '_unsettled')}
ownership_before['_modal_baseline'] = dict(ownership._modal_baseline)
runtime_timer_before = bpy.app.timers.is_registered(runtime._tick)
if runtime_timer_before:
    bpy.app.timers.unregister(runtime._tick)
bpy.context.window_manager.mixar_ui_enable(enabled=True)

def snapshot(label, pointers):
    global original
    items, hidden = observe.inventory()
    wm = bpy.context.window_manager
    raw = json.loads(wm.mixar_qa_ui_dump)
    assert not raw['pending'], raw
    windows = list(wm.windows)
    ids = {w.as_pointer(): 'w%d' % i for i, w in enumerate(windows)}
    hidden_ids = {ids[p] for p in hidden}
    result, _ = observe.observe(owner, {'limit': 200})
    owned_contexts.append(result['context'])
    assert not any(w['w'] in hidden for w in raw['widgets'])
    assert all(not w['pending'] for w in raw['windows'] if w['skipped'])
    assert not any(t['window'] in hidden_ids for t in result['targets'])
    assert not any(r['window'] in hidden_ids for r in result['regions'])
    value = {'dump': raw, 'observation': result, 'hidden': sorted(hidden),
             'window_ids': ids, 'frames': {}, 'platform': sys.platform}
    if label == 'expanded':
        island = ids[pointers['island']]
        region = next(r for r in result['regions'] if r['window'] == island
                      and r['region_type'] == 'WINDOW')
        original = (result['context'], region['target'], pointers['island'])
    elif label == 'pill':
        assert original is not None
        context, target, island = original
        if sys.platform in ('darwin', 'win32'):
            assert island in hidden, 'minimised native island must be skipped'
        else:
            # wm_draw.cc intentionally skips native hidden windows only on
            # macOS/Windows. Linux's pill remains a drawable native window.
            assert not hidden, 'unexpected Linux draw-skip semantics'
            value['hidden_capture_scope'] = 'not applicable: Linux window remains drawn'
        if hidden:
            value['hidden_capture_refusals'] = {}
            for win in windows:
                if win.as_pointer() not in hidden:
                    continue
                try:
                    observe.image(win, items, hidden)
                except UIError as error:
                    assert error.code == 'capture_unavailable', error.result()
                    value['hidden_capture_refusals'][str(win.as_pointer())] = error.result()
                else:
                    raise AssertionError('hidden frame captured without a mask inventory')
        # Run the real input entry point with its pre-minimise region handle.
        # A layout generation/region change can reject earlier than the
        # specific hidden-window guard; both must prevent native dispatch.
        action = native_input.run(owner, {'context': context, 'target': target,
                                         'action': 'press', 'key': 'ESC'})
        try:
            next(action)
        except UIError as error:
            assert error.code in ('context_changed', 'window_unavailable', 'target_changed'), error.result()
            value['old_region_action_refused'] = error.result()
        else:
            raise AssertionError('old island region action was not refused')
        finally:
            action.close()
    if label in ('expanded', 'restored'):
        island = ids[pointers['island']]
        assert any(t['window'] == island and t.get('prop') == 'mixie_chat_input'
                   for t in result['targets']), 'composer target absent after restore'
    captures = {'main': observe.main_window().as_pointer(), **pointers}
    seen = set()
    for name, pointer in captures.items():
        if pointer in seen:
            continue
        seen.add(pointer)
        win = next(w for w in windows if w.as_pointer() == pointer)
        block, frame = observe.image(win, items, hidden)
        filename = label + '-' + name + '.png'
        (out / filename).write_bytes(base64.b64decode(block['data']))
        value['frames'][name] = {'file': filename, **frame}
    return value

def start(label, pointers):
    global task, callback
    assert task is None, 'previous observation still running'
    rows[label] = {'done': False, 'pending_yields': 0}
    # Tag even the hidden island. This reproduced the old dump that could
    # never settle because drawing never consumed its region redraw flag.
    for win in bpy.context.window_manager.windows:
        for area in win.screen.areas:
            area.tag_redraw()
    rows[label]['initial_dump'] = json.loads(bpy.context.window_manager.mixar_qa_ui_dump)
    task = observe.settled(snapshot, label, pointers, timeout=5.0)
    began = time.monotonic()
    def tick():
        global task, callback
        try:
            delay = next(task)
            rows[label]['pending_yields'] += 1
            return delay
        except StopIteration as complete:
            rows[label].update(done=True, result=complete.value,
                               seconds=time.monotonic()-began)
        except Exception as error:
            rows[label].update(done=True, error=repr(error),
                               seconds=time.monotonic()-began)
        task = None
        callback = None
        return None
    callback = tick
    # The first attempt is in the same event as tag_redraw, so the pending
    # inventory is actually exercised before yielding to native drawing.
    delay = tick()
    if delay is not None:
        bpy.app.timers.register(tick, first_interval=delay)

def close():
    global task, callback
    if callback is not None and bpy.app.timers.is_registered(callback):
        bpy.app.timers.unregister(callback)
    if task is not None:
        task.close()
    for context in owned_contexts:
        observe._contexts.pop(context, None)
    ownership.release(owner)
    wm = bpy.context.window_manager
    wm.mixar_ui_end(owner=owner)
    wm.mixar_ui_enable(enabled=False)
    for name, value in ownership_before.items():
        setattr(ownership, name, value)
    if runtime_timer_before and not bpy.app.timers.is_registered(runtime._tick):
        bpy.app.timers.register(runtime._tick, first_interval=0.1, persistent=True)
    task = None
    callback = None
    return {'native_enabled': False, 'native_enabled_restored': True, 'ownership_restored': True,
            'mcp_setting_unchanged_disabled': not runtime.enabled(),
            'mirror_timer_restored': bpy.app.timers.is_registered(runtime._tick) == runtime_timer_before,
            'pending_native_events': wm.mixar_ui_pending()}
'''


def collect(qa, label, pointers):
    qa.eval(f"{NS}['start']({label!r}, {pointers!r})\nresult=True")
    qa.wait(f"{NS}['rows'][{label!r}]['done']", timeout=10)
    row = qa.eval(f"result={NS}['rows'][{label!r}]")
    (Path(os.environ['QA_SCENARIO_OUT']) / (label + '-observation.json')).write_text(json.dumps(row, indent=2))
    assert 'error' not in row, f"{label}: {row.get('error')} (full observation saved)"
    assert row['pending_yields'] > 0, 'forced redraw never exercised pending inventory'
    return row


def expanded(qa):
    qa.open_chat()
    field = {'area_type': 'AGENT_BUBBLE', 'prop': 'mixie_chat_input'}
    qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', prop='mixie_chat_input'))", timeout=10)
    # Keep the real pointer inside the island during the timer observation.
    target = qa.find(**field)['widgets'][0]
    pointer = target['window']
    rect = target['rect']
    x, y = (rect[0] + rect[2]) // 2, (rect[1] + rect[3]) // 2
    qa.eval(f"next(w for w in bpy.context.window_manager.windows if w.as_pointer()=={pointer}).cursor_warp({x}, {y})\nresult=True")
    return {'island': pointer}


def run(qa):
    out = Path(os.environ['QA_SCENARIO_OUT']).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    identity = qa.eval("import os,sys\nassert os.environ.get('MIXAR_QA')=='1'\n"
                       "result={'version':bpy.app.version_string,'blender':list(bpy.app.version),"
                       "'platform':sys.platform,'binary':bpy.app.binary_path}")
    qa.eval(f"assert {KEY!r} not in bpy.app.driver_namespace\n"
            f"{NS}={{'out':__import__('pathlib').Path({str(out)!r})}}\n"
            f"exec({APP_CODE!r}, {NS})\nresult=True")
    evidence = {'identity': identity, 'stages': {}, 'backend_turns': 0}
    try:
        evidence['stages']['expanded'] = qa.step('expanded-observe', collect, qa, 'expanded', expanded(qa))
        qa.step('minimise-native-island', qa.island_minimise)
        state = qa.island_state()
        assert state['mode'] == 'pill' and state['pill_window'], state
        evidence['pill_state'] = state
        evidence['stages']['pill'] = qa.step('pill-observe-and-refusals', collect, qa, 'pill', {'pill': state['pill_window']})
        evidence['stages']['restored'] = qa.step('restored-observe', collect, qa, 'restored', expanded(qa))
        return evidence
    finally:
        evidence['completed_stages'] = list(evidence['stages'])
        evidence['cleanup'] = qa.eval(f"result={NS}['close']()\ndel bpy.app.driver_namespace[{KEY!r}]")
        (out / 'hidden-windows.json').write_text(json.dumps(evidence, indent=2))
        qa.open_chat()


if __name__ == '__main__':
    run_scenario('blender53_hidden_windows_e2e', run)
