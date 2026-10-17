#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""AI Provider Settings shows a save's result without the pointer moving.

  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4851 \
    QA_SCENARIO_OUT=/tmp/byok-save-result \
    python3 tests/qa/byok_save_result_without_pointer_e2e.py

The regression: the save lands in ~1 s (uat6 PUT /agent/byok measured 0.6-3.2 s)
but the dialog kept drawing its previous state until the pointer moved over it,
so a user who waited saw "Validating with your provider…" for minutes. Pop-up
regions sit outside every area, so the redraw pump's `area.tag_redraw()` never
reached the dialog.

Only the network call is replaced: a worker answers after 1.3 s through the real
`byok_client._schedule_on_main` hand-off into the real save callback. The state
flip, the redraw pump and the dialog are the shipped code. The pointer is parked
on Save and never moves until the final check. No credits, no credentials.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/byok-save-result'))
OUT.mkdir(parents=True, exist_ok=True)
NET_S = 1.3
SHOW_BUDGET_S = 0.5

OPEN = """
import bpy
from mixar.modules.byok.ui.operators import byok_ops
assert not byok_ops._dialog_open, 'an AI Provider dialog is already open'
w = drv.main_window()
area = max((a for a in w.screen.areas if a.type == 'VIEW_3D'), key=lambda a: a.width * a.height)
reg = next(r for r in area.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=area, region=reg):
    result = list(bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT'))
"""

PARK_ON_SAVE = """
s = drv.find(popup=True, op='MIXAR_BYOK_OT_save')[0]
x0, y0, x1, y1 = s['rect']
drv.move_to(drv.main_window(), (x0 + x1) // 2, (y0 + y1) // 2)
result = s['rect']
"""

# What a Save click does after field validation (byok_ops.MIXAR_BYOK_OT_save),
# with save_credentials' network PUT replaced by a 1.3 s worker.
START_SAVE = f"""
import threading, time, bpy
from mixar.modules.byok.core import byok_client
from mixar.modules.byok.ui.operators import byok_ops
from mixar.modules.byok.ui.operators.byok_state_ops import ensure_dialog_redraw_pump
wm = bpy.context.window_manager
wm.byok_dialog_state = 'SAVING'
wm.byok_last_error = ''
ensure_dialog_redraw_pump()
on_done = byok_ops._save_callback()
T = bpy.app.driver_namespace['byok_save_result_qa'] = {{'t0': time.monotonic()}}
def _worker():
    time.sleep({NET_S})
    def _done(*a):
        T['t_saved'] = time.monotonic()
        on_done(*a)
    byok_client._schedule_on_main(_done, True, {{'items': [], 'byok_active': False}}, None)
threading.Thread(target=_worker, daemon=True, name='QA-BYOK-save').start()
result = True
"""

PROBE = """
import time, bpy
T = bpy.app.driver_namespace['byok_save_result_qa']
texts = [w.get('text') or '' for w in drv.find(popup=True)]
result = {
    'state': bpy.context.window_manager.byok_dialog_state,
    'saved_at': (T['t_saved'] - T['t0']) if 't_saved' in T else None,
    'since_saved': (time.monotonic() - T['t_saved']) if 't_saved' in T else None,
    'shows_done': 'Done' in texts,
    'shows_save': 'Save' in texts,
}
"""

DIALOG_CLOSED = ("not __import__('mixar.modules.byok.ui.operators.byok_ops', "
                 "fromlist=['_dialog_open'])._dialog_open")


def snap(qa, name):
    path = str(OUT / f'{name}.png')
    qa.cmd('snap', path=path, target={'popup': True, 'text': 'Done'}, margin=1500)
    return path


def result_shows_without_pointer(qa):
    """Done must be drawn within SHOW_BUDGET_S of the save landing."""
    deadline = time.monotonic() + NET_S + 10
    seen = None
    while time.monotonic() < deadline:
        seen = qa.eval(PROBE)
        if seen['saved_at'] is not None and seen['shows_done']:
            if seen['since_saved'] > SHOW_BUDGET_S:
                raise ScenarioFail(f'Done drawn {seen["since_saved"]:.2f}s after the save: {seen}')
            return seen
        if seen['saved_at'] is not None and seen['since_saved'] > SHOW_BUDGET_S:
            raise ScenarioFail('Save landed but the dialog still draws the old state '
                               f'with the pointer still: {seen}')
        time.sleep(0.05)
    raise ScenarioFail(f'The save never landed: {seen}')


def run(qa):
    # UI modules register in time-budgeted batches after startup; the splash
    # helper reads chat properties that only exist once they have.
    qa.wait("hasattr(bpy.types, 'MIXAR_BYOK_OT_open_dialog') and "
            "hasattr(bpy.types.Scene, 'mixie_chat_messages')", timeout=30)
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('open_dialog', qa.eval, OPEN)
    qa.wait("bool(drv.find(popup=True, op='MIXAR_BYOK_OT_save'))", timeout=5)
    qa.step('park_pointer_on_save', qa.eval, PARK_ON_SAVE)
    time.sleep(0.5)
    try:
        qa.step('start_save', qa.eval, START_SAVE)
        seen = qa.step('done_without_pointer_move', result_shows_without_pointer, qa)
        shot = qa.step('snap_done', snap, qa, 'saved_done')
        return {'probe': seen, 'snap': shot, 'net_s': NET_S, 'budget_s': SHOW_BUDGET_S}
    finally:
        # Esc closes through the dialog's cancel path (wipes form secrets).
        qa.step('close_dialog', qa.press, 'ESC', window=qa.eval('result = drv.main_window().as_pointer()'))
        qa.wait(DIALOG_CLOSED, timeout=5)


if __name__ == '__main__':
    run_scenario('byok_save_result_without_pointer_e2e', run)
