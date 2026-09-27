#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: an outside click collapses the island while an unrelated
temporary window (Preferences) is open elsewhere.

Regression for the open-Preferences case: any non-island temp window used to
freeze the collapse, so a Preferences window left on another display made
every click in the viewport a no-op. Run against an isolated macOS Dev app
with QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT set.
"""
import os
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario
from mixie_open_type_send_e2e import FIELD, SCENE, open_pill, press, snap
from mixie_window_interaction_e2e import host_event, visible

PREFS = ("[w for w in bpy.context.window_manager.windows "
         "if w.screen.is_temporary and any(a.type == 'PREFERENCES' for a in w.screen.areas)]")


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def prefs_open(qa):
    return qa.eval(f'result=len({PREFS})')


def close_prefs(qa):
    qa.eval(f'wins={PREFS}\n'
            'for w in wins:\n'
            '    with bpy.context.temp_override(window=w):\n'
            '        bpy.ops.wm.window_close()\n'
            'result=True')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/mixie-window-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    qa.eval(f'import sys, importlib; sys.path.insert(0,{str(Path(__file__).parent)!r}); '
            'import mixie_window_native as n; importlib.reload(n); result=True')
    if qa.find(**FIELD)['total']:
        press(qa, 'ESC')
    qa.eval(f'scene={SCENE}; scene.mixie_chat_input=""; '
            'scene.mixie_chat_messages.clear(); result=True')
    close_prefs(qa)

    # Baseline: no temp window, outside click collapses.
    open_pill(qa)
    require(visible(qa), 'island did not open')
    host_event(qa)
    host_event(qa, value='RELEASE')
    time.sleep(.4)
    require(not visible(qa), 'baseline outside click did not collapse')
    qa.step('outside_click_collapses_without_temp_window', lambda: True)

    # Preferences is a temp screen in its own window, parented to the host.
    qa.eval('w=drv.main_window()\n'
            'with bpy.context.temp_override(window=w):\n'
            '    bpy.ops.screen.userpref_show()\n'
            'result=True')
    time.sleep(.6)
    require(prefs_open(qa) == 1, 'Preferences window did not open as a temp window')
    try:
        open_pill(qa)
        require(visible(qa), 'island did not reopen with Preferences open')
        snap(qa, out, 'island-open-with-preferences')
        host_event(qa)
        host_event(qa, value='RELEASE')
        time.sleep(.4)
        require(not visible(qa), 'outside click did not collapse while Preferences was open')
        require(prefs_open(qa) == 1, 'collapsing the island closed Preferences')
        # The hidden island keeps its last frame; the pill is the picture of collapsed.
        time.sleep(.35)
        qa.cmd('snap', path=str(out / 'collapsed-with-preferences-pill.png'),
               target={'surface': 'pill_cat'}, margin=400)
        qa.step('outside_click_collapses_with_preferences_open', lambda: True)
    finally:
        close_prefs(qa)
    require(prefs_open(qa) == 0, 'could not close Preferences')


if __name__ == '__main__':
    run_scenario('mixie_outside_click_temp_window_e2e', run)
