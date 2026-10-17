#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""AI Provider Settings through `wm.mixar_invoke_modal_dialog`, from BOTH entry
points, under the agent viewport lock. No credits, no real credentials.

  QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4851 \
    QA_SCENARIO_OUT=/tmp/modal-dialog-docks \
    python3 tests/qa/modal_dialog_docks_lock_e2e.py

Run on an isolated QA app built with the change. For each entry point —
(A) the island model chip's popup with the island OPEN and a draft typed,
(B) the profile menu with the island resting as the PILL — it proves:
1. the dialog is hosted in the main window and centred in it;
2. every floating dock that was on screen is suppressed (macOS: native
   NSWindow alpha 0 + ignoresMouseEvents; `wm.windows` still lists alpha-0
   windows, so only the native read is trusted);
3. with BUSY/AGENT forced (the real bootstrap starts the real lock + halo), a
   click into the API-key field and a key containing "s" reach the dialog;
4. Cancel closes it under the lock and wipes the field;
5. the docks come back exactly as before (A: island open, draft intact;
   B: resting pill), natively visible again;
6. G over the viewport is still blocked by the lock afterwards.
Only the provider catalog and the signed-in profile label are fixtures; clicks,
keys, operators, the lock modal and the native dock suppression are real.
Read the saved PNGs too.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bubble_new_file_from_island_e2e import NATIVE_WINDOWS  # noqa: E402
import model_popup as mp  # noqa: E402

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/modal-dialog-docks'))
OUT.mkdir(parents=True, exist_ok=True)
USER = 'qa.modal-dialog@example.invalid'
PROFILE = {'text': USER, 'area_type': 'TOPBAR'}
SETTINGS = {'op': 'MIXAR_BYOK_OT_open_dialog', 'popup': True}
KEY_FIELD = {'prop': 'byok_form_api_key', 'popup': True}
WM = 'bpy.context.window_manager'
SCENE = 'drv.main_window().scene'
DRAFT = 'qa draft that must survive the dialog'
TYPED = 'qa-s3cret-keys'
LOCK = ("__import__('mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op', "
        "fromlist=['is_running']).is_running()")
DIALOG_OPEN = "bool(drv.find(op='MIXAR_BYOK_OT_save', popup=True))"

SETUP = f"""
import bpy, copy, os
from mixar.modules.byok.core import credential_state as C, model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
assert os.environ.get('MIXAR_QA') == '1'
assert hasattr(bpy.context.window_manager, 'mixar_invoke_modal_dialog'), 'build lacks the native dialog'
wm = bpy.context.window_manager
scene = drv.main_window().scene
saved = (C.snapshot(), list(M._provider_cache), copy.deepcopy(M._model_cache),
         copy.deepcopy(M._platform_records), M.is_loaded(),
         bpy.context.preferences.view.show_tooltips, wm.mixie_chat_is_logged_in,
         scene.mixie_chat_user_id, scene.mixie_chat_input)
M.populate_from_payload({{'providers': [{{'id': 'openai', 'label': 'QA Provider',
    'models': [{{'id': 'qa-one', 'label': 'QA Model One', 'platform_available': True}}]}}]}})
C.clear()
wm.byok_form_provider = 'openai'
wm.mixie_chat_is_logged_in = True
scene.mixie_chat_user_id = {USER!r}
bpy.context.preferences.view.show_tooltips = False
O._qa_modal_dialog_fixture = saved
result = True
"""
CLEANUP = """
from mixar.modules.byok.core import credential_state as C, model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
saved = O._qa_modal_dialog_fixture
C.clear()
with C._lock:
    C._state = saved[0]
C.apply_to_wm()
M.populate(saved[1], saved[2], saved[3])
M._populated_once = saved[4]
bpy.context.preferences.view.show_tooltips = saved[5]
bpy.context.window_manager.mixie_chat_is_logged_in = saved[6]
scene = drv.main_window().scene
scene.mixie_chat_user_id = saved[7]
scene.mixie_chat_input = saved[8]
O._wipe_form_secrets(bpy.context.window_manager)
del O._qa_modal_dialog_fixture
result = True
"""
# The dialog's own region (the key field's), in main-window pixels. Read from
# the raw dump: the driver drops the region pointer, and pop-up regions are in
# no area, so it is the only way to tell the dialog from a popover under it.
GEOMETRY = """
import json
main = drv.main_window()
raw = json.loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets']
key = next(w for w in raw if w.get('popup') and w.get('prop') == 'byok_form_api_key')
assert key['w'] == main.as_pointer(), 'dialog is not hosted in the main window'
rects = [w['rect'] for w in raw if w.get('popup') and w['w'] == key['w'] and w['r'] == key['r']]
result = {'dialog': [min(r[0] for r in rects), min(r[1] for r in rects),
                     max(r[2] for r in rects), max(r[3] for r in rects)],
          # Widget rects are framebuffer pixels; Window.width/height are
          # logical (half on Retina). Areas tile the window in pixels.
          'size': [max(a.x + a.width for a in main.screen.areas),
                   max(a.y + a.height for a in main.screen.areas)]}
"""


def native_docks(qa):
    """Floating docks as AppKit sees them (None off macOS)."""
    return qa.eval(NATIVE_WINDOWS)


def settled_docks(qa, timeout=3.0):
    """Docks once no fade is in flight. The pill and island cross-fade through
    AppKit's animator for ~0.3 s after they open or close; a reading taken
    mid-fade (alpha 0.84 on a fresh launch) is not a state to restore to."""
    deadline = time.monotonic() + timeout
    docks = native_docks(qa)
    while docks is not None and time.monotonic() < deadline:
        if all(not d['visible'] or d['alpha'] in (0.0, 1.0) for d in docks):
            break
        time.sleep(0.1)
        docks = native_docks(qa)
    return docks


def _on_screen(docks):
    # Island and pill share titles, and the pill's changes after launch
    # ("Agent Bubble Status" -> "Agent Bubble"): compare counts, not titles.
    return [d for d in docks if d['visible'] and d['alpha'] > 0.5]


def snap(qa, name):
    qa.eval("w = drv.main_window()\n"
            "with bpy.context.temp_override(window=w, area=next(iter(w.screen.areas))):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result = True")
    time.sleep(.5)
    path = str(OUT / (name + '.png'))
    qa.cmd('snap', path=path, target=KEY_FIELD, margin=1500)
    return path


def open_from_island(qa):
    # The model chip's popup; its key tab's footer is the settings route
    # ("Add a key…" / "Manage key…" / "Enter key…", whichever applies).
    mp.open_settings(qa)
    qa.wait(DIALOG_OPEN, timeout=10)
    return True


def open_from_profile(qa):
    qa.click(**PROFILE)
    qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))", timeout=5)
    qa.click(**SETTINGS)
    qa.wait(DIALOG_OPEN, timeout=10)
    return True


def dialog_centred(qa):
    geo = qa.eval(GEOMETRY)
    (x0, y0, x1, y1), (w, h) = geo['dialog'], geo['size']
    if abs((x0 + x1) / 2 - w / 2) > 0.08 * w or abs((y0 + y1) / 2 - h / 2) > 0.12 * h:
        raise ScenarioFail(f'Dialog not centred in the main window: {geo}')
    return geo


def docks_suppressed(qa, before):
    during = native_docks(qa)
    if during is None:
        return None  # Windows hides with SW_HIDE; no AppKit read
    if not _on_screen(before):
        raise ScenarioFail(f'No floating dock was on screen before the dialog: {before}')
    # An ordered-out window (the minimised island) is off screen already, so
    # only judge the ones still ordered in.
    for dock in during:
        if dock['visible'] and not (dock['alpha'] == 0.0 and dock['ignores_mouse']):
            raise ScenarioFail(f'Floating dock still on screen under the dialog: {during}')
    return during


def busy(qa, state):
    qa.eval(f"{SCENE}.mixie_chat_active_turn_mode = 'AGENT'\n"
            f"{SCENE}.mixie_chat_state = {state!r}\nresult = True")
    qa.wait(f"{LOCK} == {state == 'BUSY'}", timeout=5)
    return True


def type_key_under_lock(qa):
    qa.click(**KEY_FIELD)  # a click over the locked viewport rectangle
    time.sleep(.2)
    qa.cmd('type', text=TYPED)  # "s" is a lock-blocked hotkey
    qa.press('RET')
    qa.wait(f"{WM}.byok_form_api_key == {TYPED!r}", timeout=5)
    if not qa.eval(f'result = {LOCK}'):
        raise ScenarioFail('Typing in the dialog dropped the lock')
    return True


def cancel_under_lock(qa):
    # The sheet's close is the ✕ (a template_popup_confirm cancel button, the
    # same cancel() path Esc takes); older dialogs said "Cancel".
    closer = '✕' if qa.find(text='✕', popup=True)['widgets'] else 'Cancel'
    qa.click(text=closer, popup=True)
    qa.wait(f'not {DIALOG_OPEN}', timeout=5)
    if qa.eval(f'result = {WM}.byok_form_api_key'):
        raise ScenarioFail('Cancel left the typed key in RNA memory')
    return True


def docks_restored(qa, before, mode):
    qa.wait(f"drv.island_state()['mode'] == {mode!r}", timeout=10)
    after = settled_docks(qa)
    if after is not None:
        back = [d for d in _on_screen(after) if not d['ignores_mouse']]
        if len(back) < len(_on_screen(before)):
            raise ScenarioFail(f'Docks not restored as they were: {before} -> {after}')
    return after


def viewport_still_locked(qa):
    before = qa.eval("result = {o.name: list(o.location) for o in bpy.data.objects}")
    qa.eval("w = drv.main_window()\n"
            "drv.move_to(w, w.width // 2, w.height // 2)\nresult = True")
    qa.press('G')
    qa.eval("w = drv.main_window()\n"
            "drv.move_to(w, w.width // 2 + 60, w.height // 2 + 30)\nresult = True")
    qa.press('RET')
    if qa.eval("result = {o.name: list(o.location) for o in bpy.data.objects}") != before:
        raise ScenarioFail('The viewport accepted a transform under the lock')
    if not qa.eval(f'result = {LOCK}'):
        raise ScenarioFail('The lock ended with the dialog')
    return True


def close_popups(qa):
    for _ in range(3):
        widgets = qa.find(popup=True)['widgets']
        if not widgets:
            return
        for window in {w['window'] for w in widgets}:
            qa.press('ESC', window=window)
        time.sleep(.2)


def exercise(qa, name, open_fn, mode):
    """One entry point, end to end; `mode` is the island state to come back to."""
    before = settled_docks(qa)
    qa.step(f'{name}_open', open_fn, qa)
    geo = qa.step(f'{name}_centred', dialog_centred, qa)
    if before is not None:
        qa.step(f'{name}_docks_suppressed', docks_suppressed, qa, before)
    shots = [qa.step(f'{name}_snap_open', snap, qa, f'{name}_01_open')]
    qa.step(f'{name}_force_busy', busy, qa, 'BUSY')
    shots.append(qa.step(f'{name}_snap_busy', snap, qa, f'{name}_02_under_halo'))
    qa.step(f'{name}_type_key_under_lock', type_key_under_lock, qa)
    qa.step(f'{name}_cancel_under_lock', cancel_under_lock, qa)
    close_popups(qa)  # the profile popover stays under its dialog
    if before is not None:
        qa.step(f'{name}_docks_restored', docks_restored, qa, before, mode)
    else:
        qa.wait(f"drv.island_state()['mode'] == {mode!r}", timeout=10)
    qa.step(f'{name}_viewport_still_locked', viewport_still_locked, qa)
    qa.step(f'{name}_idle', busy, qa, 'IDLE')
    return {'geometry': geo, 'snaps': shots}


STARTUP_PROBE = ("s = drv.main_window().scene\n"
                 "wm = bpy.context.window_manager\n"
                 "result = [s.mixie_chat_state, wm.mixie_chat_is_logged_in, "
                 "wm.mixie_chat_is_guest, s.mixie_chat_user_id]")


def settle_startup(qa, quiet_s=2.0, timeout=45.0):
    """A fresh launch signs in and connects for a few seconds (OFFLINE ->
    CONNECTING -> IDLE, the profile label filled in). Forcing BUSY or the
    profile fixture before that ends gets overwritten mid-scenario, so wait
    until the chat state has been quiet for `quiet_s`."""
    qa.wait("hasattr(bpy.types, 'MIXAR_BYOK_OT_open_dialog') and "
            "hasattr(bpy.types.Scene, 'mixie_chat_messages')", timeout=30)
    deadline = time.monotonic() + timeout
    last, since = None, time.monotonic()
    while time.monotonic() < deadline:
        now = qa.eval(STARTUP_PROBE)
        if now != last:
            last, since = now, time.monotonic()
        elif now[0] != 'CONNECTING' and time.monotonic() - since >= quiet_s:
            return now
        time.sleep(0.25)
    raise ScenarioFail(f'App never settled after launch: {last}')


def run(qa):
    qa.step('settle_startup', settle_startup, qa)
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('install_fixture', qa.eval, SETUP)
    results = {}
    try:
        # (A) island open with a draft → model dropdown.
        # From the resting pill, open the island the way a user does (the
        # restore is what focuses the composer for typing).
        if qa.eval("result = drv.island_state()['mode']") != 'pill':
            qa.island_minimise()
            qa.wait("drv.island_state()['mode'] == 'pill'", timeout=10)
        qa.step('open_island', qa.open_chat)
        qa.wait("drv.island_state()['mode'] == 'island'", timeout=10)
        # Type the draft like a user: the open island has focused its composer,
        # and a property write under an active edit buffer is overwritten when
        # editing ends.
        composer = qa.find(prop='mixie_chat_input', area_type='AGENT_BUBBLE')['widgets'][0]
        qa.step('type_draft', qa.cmd, 'type', window=composer['window'], text=DRAFT)
        qa.wait(f"{SCENE}.mixie_chat_input == {DRAFT!r}", timeout=5)
        results['island'] = exercise(qa, 'island', open_from_island, 'island')
        if qa.eval(f'result = {SCENE}.mixie_chat_input') != DRAFT:
            raise ScenarioFail('The island draft did not survive the dialog')
        # (B) island resting as the pill → profile menu.
        qa.step('rest_as_pill', qa.island_minimise)
        qa.wait("drv.island_state()['mode'] == 'pill'", timeout=10)
        results['profile'] = exercise(qa, 'profile', open_from_profile, 'pill')
        results['fixture'] = 'catalog + profile label; BUSY/AGENT without a backend turn'
        return results
    finally:
        close_popups(qa)
        busy(qa, 'IDLE')
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('modal_dialog_docks_lock_e2e', run)
