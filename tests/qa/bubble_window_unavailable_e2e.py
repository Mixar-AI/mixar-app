#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""A bubble window that cannot be created is tried once, not 70 times.

Prod 4.4.0, Windows, AMD integrated GPU: the OS refused the Agent Bubble
window a GL context, so ``mixar.agent_bubble_show_window`` failed with
"Failed to open Agent Bubble window". The file-load tick retried it every
0.25 s up to 40 times and the autoshow loop 30 more; on Windows each attempt
also raised a modal "Unsupported Graphics Card" box over a working app.

The GL failure itself is Windows-only, so this replays it through Python:
the bubble operators, as seen by the autoshow code (``bubble_autoshow.bpy``)
and by the explicit open operator (``window_ops.bpy``), raise exactly the
RuntimeError the native operator raises, and count each call. Everything
else (timers, the real ``load_post`` handler, ``arm_autoshow``, the bubble
state) is the app's own.

Steps: close the island and pill, run the app's ``load_post`` handler (what a
file load does) and arm autoshow (what a workspace change does), wait 18 s,
then count. Run the handler again (the next file load), then the explicit
opens (``mixar.agent_bubble_open_window``, ``mixar.open_mixie``), then
restore: a real explicit open, and autoshow again.

Expected:
- FIXED build: 1 failed attempt in total, every retry timer stopped,
  ``bubble_state.window_unavailable`` latched; the next file load clears it
  and tries exactly once more; each explicit open still tries exactly once;
  after the real explicit open the latch is clear and autoshow brings the
  pill back. PASS.
- UNFIXED build (PR #1983 tip before this fix): ~70 failed attempts (40 from
  the file-load tick, 30 from autoshow) in the 18 s window. FAIL at
  ``no_retry_storm``.

Runs on macOS (or any platform) against a built app; no backend, no credits.
Export QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble_window_unavailable'))
OUT.mkdir(parents=True, exist_ok=True)

# Long enough for the unfixed build to exhaust both retry budgets
# (file-load: 0.1 s + 40 x 0.25 s; autoshow: 0.5 s + 30 x 0.5 s).
STORM_WINDOW_S = 18

COUNT = "bpy.app.driver_namespace.get('qa_bubble_fail_calls', 0)"

# Wrap the module-level ``bpy`` of the autoshow code and of the open
# operator so the two bubble operators fail like the native one does when
# WM_window_open returns no window. Every other attribute is the real bpy.
INSTALL_FAILURE = r'''
import sys
from mixar.modules.agent_bubble.core import bubble_autoshow as _ba
from mixar.modules.agent_bubble.core import bubble_state as _st

ns = bpy.app.driver_namespace
ns['qa_bubble_fail_calls'] = 0
_real_bpy = bpy

def _fail(*_a, **_k):
    ns['qa_bubble_fail_calls'] += 1
    raise RuntimeError('Error: Failed to open Agent Bubble window\n')

class _Mixar:
    def __getattr__(self, name):
        if name in ('agent_bubble_show_window', 'agent_bubble_open_window'):
            return _fail
        return getattr(_real_bpy.ops.mixar, name)

class _Ops:
    mixar = _Mixar()
    def __getattr__(self, name):
        return getattr(_real_bpy.ops, name)

class _Bpy:
    ops = _Ops()
    def __getattr__(self, name):
        return getattr(_real_bpy, name)

cls = getattr(bpy.types, 'MIXAR_OT_agent_bubble_open_window', None)
window_ops = sys.modules.get(getattr(cls, '__module__', ''), None)
if window_ops is None or not hasattr(window_ops, 'MIXAR_OT_agent_bubble_open_window'):
    window_ops = next(m for n, m in list(sys.modules.items())
                      if n.endswith('window_ops') and hasattr(m, 'MIXAR_OT_agent_bubble_open_window'))
fake = _Bpy()
ns['qa_bubble_patched'] = [(_ba, _ba.bpy), (window_ops, window_ops.bpy)]
_ba.bpy = fake
window_ops.bpy = fake
_st.window_unavailable = False   # harmless on a build without the latch
result = {'window_ops': window_ops.__name__}
'''

REMOVE_FAILURE = r'''
ns = bpy.app.driver_namespace
for module, original in ns.pop('qa_bubble_patched', []):
    module.bpy = original
result = True
'''

CLOSE_BUBBLE = r'''
from mixar.modules.agent_bubble.core import bubble_lifecycle as _bl
for timer in (_bl.load_autoshow_tick,
              __import__('mixar.modules.agent_bubble.core.bubble_autoshow',
                         fromlist=['x']).autoshow_bubble):
    if bpy.app.timers.is_registered(timer):
        bpy.app.timers.unregister(timer)
_bl.close_restored_agent_bubble_windows()
result = _bl.has_agent_bubble_windows()
'''

# What a file load runs (the app's own load_post handler), then what a
# workspace change runs (arm_autoshow).
TRIGGER_RETRIES = r'''
from mixar.modules.agent_bubble.core.bubble_autoshow import arm_autoshow
handler = next(h for h in bpy.app.handlers.load_post
               if getattr(h, '__name__', '') == '_on_load_post')
handler(None)
arm_autoshow(reset=True, start_minimised=True)
result = True
'''

STATE = r'''
from mixar.modules.agent_bubble.core import bubble_autoshow as _ba
from mixar.modules.agent_bubble.core import bubble_lifecycle as _bl
from mixar.modules.agent_bubble.core import bubble_state as _st
result = {
    'fail_calls': bpy.app.driver_namespace.get('qa_bubble_fail_calls', 0),
    'load_tick_registered': bpy.app.timers.is_registered(_bl.load_autoshow_tick),
    'reset_registered': bpy.app.timers.is_registered(_bl.reset_restored_bubbles_after_load),
    'autoshow_registered': bpy.app.timers.is_registered(_ba.autoshow_bubble),
    'window_unavailable': getattr(_st, 'window_unavailable', None),
    'bubble_windows': _bl.has_agent_bubble_windows(),
}
'''

EXPLICIT_OPEN = r'''
before = bpy.app.driver_namespace['qa_bubble_fail_calls']
error = None
with bpy.context.temp_override(window=drv.main_window()):
    try:
        bpy.ops.mixar.agent_bubble_open_window()
    except RuntimeError as exc:
        error = str(exc)
result = {'tries': bpy.app.driver_namespace['qa_bubble_fail_calls'] - before, 'error': error}
'''

SHIFT_M_OPEN = r'''
before = bpy.app.driver_namespace['qa_bubble_fail_calls']
with bpy.context.temp_override(window=drv.main_window()):
    status = sorted(bpy.ops.mixar.open_mixie())
result = {'tries': bpy.app.driver_namespace['qa_bubble_fail_calls'] - before, 'status': status}
'''

REAL_OPEN = r'''
from mixar.modules.agent_bubble.core import bubble_lifecycle as _bl
from mixar.modules.agent_bubble.core import bubble_state as _st
with bpy.context.temp_override(window=drv.main_window()):
    status = sorted(bpy.ops.mixar.agent_bubble_open_window())
result = {'status': status, 'bubble_windows': _bl.has_agent_bubble_windows(),
          'window_unavailable': getattr(_st, 'window_unavailable', None)}
'''

TRIGGER_LOAD = r'''
handler = next(h for h in bpy.app.handlers.load_post
               if getattr(h, '__name__', '') == '_on_load_post')
handler(None)
result = True
'''

REARM = r'''
from mixar.modules.agent_bubble.core.bubble_autoshow import arm_autoshow
arm_autoshow(reset=True, start_minimised=True)
result = True
'''


def snap(qa, name):
    path = str(OUT / name)
    qa.snap(path)
    return path


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('pill_up_before', qa.wait, "drv.island_state()['mode'] in ('pill', 'island')",
            timeout=30)
    snaps = [qa.step('snap_before', snap, qa, 'before.png')]

    patched = qa.step('install_failure', qa.eval, INSTALL_FAILURE)
    try:
        if qa.step('close_bubble', qa.eval, CLOSE_BUBBLE):
            raise ScenarioFail('bubble windows survived the close')
        qa.step('trigger_load_and_autoshow', qa.eval, TRIGGER_RETRIES)
        time.sleep(STORM_WINDOW_S)
        storm = qa.step('state_after_storm_window', qa.eval, STATE)
        snaps.append(qa.step('snap_after_storm', snap, qa, 'after-storm-window.png'))
        if storm['fail_calls'] != 1:
            qa.step('no_retry_storm', _raise,
                    f"{storm['fail_calls']} failed bubble-window attempts in "
                    f"{STORM_WINDOW_S}s, expected 1: {storm}")
        if storm['load_tick_registered'] or storm['autoshow_registered'] or storm['reset_registered']:
            qa.step('retry_timers_stopped', _raise, f'retry timers still armed: {storm}')
        if storm['window_unavailable'] is not True:
            qa.step('latch_set', _raise, f'window_unavailable not latched: {storm}')
        if storm['bubble_windows']:
            raise ScenarioFail(f'a bubble window exists while open is failing: {storm}')

        qa.step('next_file_load', qa.eval, TRIGGER_LOAD)
        time.sleep(3)
        reload = qa.step('next_load_tries_once', qa.eval, STATE)
        if (reload['fail_calls'] != 2 or reload['window_unavailable'] is not True
                or reload['load_tick_registered'] or reload['reset_registered']):
            raise ScenarioFail(f'the next file load did not try exactly once more: {reload}')

        explicit = qa.step('explicit_open_tries_once', qa.eval, EXPLICIT_OPEN)
        if explicit['tries'] != 1 or 'Failed to open Agent Bubble window' not in (explicit['error'] or ''):
            raise ScenarioFail(f'explicit open did not try once and report: {explicit}')
        shift_m = qa.step('shift_m_tries_once', qa.eval, SHIFT_M_OPEN)
        if shift_m['tries'] != 1 or shift_m['status'] != ['FINISHED']:
            raise ScenarioFail(f'Shift+M open did not try once: {shift_m}')
        snaps.append(qa.step('snap_after_explicit', snap, qa, 'after-explicit-open.png'))
        after_explicit = qa.step('no_retries_after_explicit', qa.eval, STATE)
        if after_explicit['load_tick_registered'] or after_explicit['autoshow_registered']:
            raise ScenarioFail(f'an explicit open re-armed the retry loops: {after_explicit}')
    finally:
        qa.step('remove_failure', qa.eval, REMOVE_FAILURE)

    real = qa.step('real_explicit_open', qa.eval, REAL_OPEN)
    if real['status'] != ['FINISHED'] or not real['bubble_windows']:
        raise ScenarioFail(f'the real explicit open did not open the bubble: {real}')
    if real['window_unavailable'] is not False:
        raise ScenarioFail(f'a successful explicit open left the latch set: {real}')
    qa.step('close_again', qa.eval, CLOSE_BUBBLE)
    qa.step('rearm_autoshow', qa.eval, REARM)
    qa.step('autoshow_brings_pill_back', qa.wait, "drv.island_state()['mode'] == 'pill'",
            timeout=20)
    snaps.append(qa.step('snap_restored', snap, qa, 'restored.png'))
    return {'patched': patched, 'storm': storm, 'next_load': reload,
            'explicit': explicit, 'shift_m': shift_m,
            'real_open': real, 'snapshots': snaps}


def _raise(message):
    raise ScenarioFail(message)


if __name__ == '__main__':
    run_scenario('bubble_window_unavailable', run)
