#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Profile and the floating chat picker share provider settings, in both directions.

Run against an isolated offline QA instance. Only the HTTP service boundary
and catalog are fixtures; clicks, forms, worker threads and timers are real.
No real credentials are read or sent. All replaced state is restored.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4791 \
    QA_SCENARIO_OUT=/tmp/profile-provider-qa python3 tests/qa/profile_provider_settings_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/profile-provider-qa'))
OUT.mkdir(parents=True, exist_ok=True)
PROFILE = {'text': 'qa.provider@example.invalid', 'area_type': 'TOPBAR'}
SETTINGS = {'op': 'MIXAR_BYOK_OT_open_dialog', 'popup': True}
SAVE = {'op': 'MIXAR_BYOK_OT_save', 'popup': True}
WM = 'bpy.context.window_manager'

SETUP = """
import bpy, copy, os
from types import SimpleNamespace
from mixar.modules.byok.core import byok_client as B, preference_client as F
from mixar.modules.byok.core import credential_state as C, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
assert os.environ.get('MIXAR_QA') == '1'
wm = bpy.context.window_manager
saved = (B.get_agent_service, F.get_agent_service,
         O._deregister_local_if_switched_away, C.snapshot(), P.snapshot(),
         list(M._provider_cache), copy.deepcopy(M._model_cache),
         copy.deepcopy(M._platform_records), M.is_loaded(),
         wm.mixie_chat_is_logged_in, bpy.context.scene.mixie_chat_user_id,
         bpy.context.preferences.view.show_tooltips)
fixture = SimpleNamespace(active=False, model='', saves=0, deletes=0, fetches=0,
                          switches=0, rejected=0, reject_next=False, enabled=True,
                          pauses=0, resumes=0, state_rejected=0, reject_state_next=False)
def response(data):
    return SimpleNamespace(success=True, status_code=200, data={'data': data})
# `active` = a key is stored; `enabled` = not paused by the island toggle
# (the backend's contract: byok_active needs both).
def payload():
    return {'byok_active': fixture.active and fixture.enabled, 'items': [{'provider': 'openai',
            'model': fixture.model, 'key_preview': 'QA fixture', 'enabled': fixture.enabled,
            'is_valid': True}] if fixture.active else []}
def get_preference():
    fixture.fetches += 1
    return response({'byok_active': fixture.active and fixture.enabled, 'items': []})
def save_credentials(**kwargs):
    if kwargs.get('keep_stored_key'):
        # The island chip's switch: no key on the wire, the stored one reused
        # for the same provider (the backend contract), re-validated.
        assert kwargs['api_key'] is None and fixture.active and kwargs['provider'] == 'openai'
        if fixture.reject_next:
            fixture.reject_next = False
            fixture.rejected += 1
            return SimpleNamespace(success=False, status_code=400,
                data={'status': 'failure', 'message': 'Model not available: QA rejection'})
        fixture.switches += 1
        fixture.model, fixture.enabled = kwargs['model'], True
        return response(payload())
    assert kwargs['api_key'] == 'qa-synthetic-key'
    fixture.saves += 1
    fixture.active, fixture.model, fixture.enabled = True, kwargs['model'], True
    return response(payload())
def set_byok_state(enabled):
    if fixture.reject_state_next:
        fixture.reject_state_next = False
        fixture.state_rejected += 1
        return SimpleNamespace(success=False, status_code=502,
            data={'status': 'failure', 'message': 'Provider unreachable: QA rejection'})
    if not fixture.active:
        return SimpleNamespace(success=False, status_code=400,
            data={'status': 'failure', 'message': 'No saved API key'})
    fixture.enabled = bool(enabled)
    if enabled:
        fixture.resumes += 1
    else:
        fixture.pauses += 1
    return response(payload())
def delete_credentials():
    fixture.deletes += 1
    fixture.active, fixture.model, fixture.enabled = False, '', True
    return response({'removed': 1})
service = SimpleNamespace(get_model_preference=get_preference,
    get_credentials=lambda: response(payload()), save_credentials_all=save_credentials,
    delete_credentials_all=delete_credentials, set_byok_state=set_byok_state)
B.get_agent_service = F.get_agent_service = lambda: service
O._deregister_local_if_switched_away = lambda provider: None
M.populate_from_payload({'providers': [{'id': 'openai', 'label': 'QA Provider',
    'models': [{'id': 'qa-one', 'label': 'QA Model One', 'platform_available': True},
               {'id': 'qa-two', 'label': 'QA Model Two', 'platform_available': True}]}]})
C.clear()
P.clear()
wm.byok_form_provider = 'openai'
wm.mixie_chat_is_logged_in = True
bpy.context.scene.mixie_chat_user_id = 'qa.provider@example.invalid'
bpy.context.preferences.view.show_tooltips = False
P._redraw()
O._qa_profile_fixture = (saved, fixture)
result = True
"""

CLEANUP = """
from mixar.modules.byok.core import byok_client as B, preference_client as F
from mixar.modules.byok.core import credential_state as C, preference_state as P
from mixar.modules.byok.core import model_suggestions as M
from mixar.modules.byok.ui.operators import byok_ops as O
saved, fixture = O._qa_profile_fixture
B.get_agent_service, F.get_agent_service = saved[:2]
O._deregister_local_if_switched_away = saved[2]
C.clear()
with C._lock:
    C._state = saved[3]
C.apply_to_wm()
P.clear()
P.apply_local(saved[4])
M.populate(saved[5], saved[6], saved[7])
M._populated_once = saved[8]
bpy.context.window_manager.mixie_chat_is_logged_in = saved[9]
bpy.context.scene.mixie_chat_user_id = saved[10]
bpy.context.preferences.view.show_tooltips = saved[11]
O._wipe_form_secrets(bpy.context.window_manager)
del O._qa_profile_fixture
result = True
"""


def close_popup(qa):
    # The profile popover remains underneath its modal provider dialog.
    # Dismiss each layer rather than assuming one Escape closes both.
    for _ in range(3):
        widgets = qa.find(popup=True)['widgets']
        if not widgets:
            return
        for window in {w['window'] for w in widgets}:
            qa.press('ESC', window=window)
        time.sleep(.2)
    qa.wait('not bool(drv.find(popup=True))', timeout=5)


def snap(qa, name, target):
    # A rehosted popup can have current layout data while the inactive host
    # still presents its preceding frame. Flush that window before reading
    # its framebuffer; ordinary area redraw tags do not cover popup regions.
    qa.eval(f"widget=drv.find_one(**{target!r})\n"
            "win=widget['_win']\n"
            "area=next(iter(win.screen.areas))\n"
            "with bpy.context.temp_override(window=win, area=area):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(1)
    path = str(OUT / (name + '.png'))
    qa.step(name + '_snap', qa.cmd, 'snap', path=path, target=target, margin=1500)
    return path


def open_profile(qa, name):
    qa.step(name + '_profile', qa.click, **PROFILE)
    hits = qa.find(**SETTINGS)['widgets']
    if len(hits) != 1 or not hits[0]['enabled']:
        raise ScenarioFail(f'Profile settings missing or disabled: {hits}')
    path = snap(qa, name + '_profile', SETTINGS)
    qa.step(name + '_settings', qa.click, **SETTINGS)
    check_dialog(qa)
    return path


def check_dialog(qa):
    qa.wait("any(w.get('popup') and w.get('op') == 'MIXAR_BYOK_OT_save' "
            "for w in __import__('json').loads(bpy.data.window_managers[0].mixar_qa_ui_dump)['widgets'])",
            timeout=10)
    dialog = qa.find(**SAVE)['widgets'][0]
    areas = qa.eval(f"result = [a.type for w in bpy.context.window_manager.windows "
                    f"if w.as_pointer() == {dialog['window']} for a in w.screen.areas]")
    if 'AGENT_BUBBLE' in areas:
        raise ScenarioFail('Provider settings was clipped into the island window')


def key_half(qa):
    """The island toggle's Custom AI half (`mixar_byok.use_key`)."""
    halves = qa.find(op='MIXAR_BYOK_OT_use_key', area_type='AGENT_BUBBLE')['widgets']
    if len(halves) != 1:
        raise ScenarioFail(f'Island Mixie | Custom AI toggle missing: {halves}')
    return halves[0]


def click_key_half(qa):
    half = key_half(qa)
    qa.cmd('click_xy', x=half['center'][0], y=half['center'][1], window=half['window'])


def open_picker(qa, area_type, active):
    if area_type == 'AGENT_BUBBLE':
        qa.eval('result=str(bpy.ops.mixar.agent_bubble_show_window())')
    if active:
        # A key in use: Custom AI opens the shared dialog, Mixie switches
        # back (a pause, no dialog), and the only pulldown left on the row is
        # the key chip's model switch, right of the toggle — the hosted menu
        # is not offered over the key.
        key = qa.find(op='MIXAR_BYOK_OT_use_key', area_type=area_type)['widgets']
        mixie = qa.find(op='MIXAR_BYOK_OT_use_mixie', area_type=area_type)['widgets']
        pulls = qa.find(but_type='Pulldown', area_type=area_type, region_type='TOOLS')['widgets']
        if (len(key) != 1 or len(mixie) != 1 or len(pulls) != 1
                or pulls[0]['rect'][0] <= key[0]['rect'][0]):
            raise ScenarioFail(f'{area_type} toggle does not show the key in use: '
                               f'{key} {mixie} {pulls}')
        return
    # The settings dialog pills the island while it is up and restores it on
    # close; let that land. The first native click after the island comes
    # back can commit composer focus instead (agent_model_chip_label_e2e):
    # retry once, only when the menu demonstrably stayed shut.
    qa.wait("not __import__('mixar.modules.byok.ui.operators.byok_dialog_host', "
            "fromlist=['x'])._island_minimised", timeout=5)
    for _ in range(2):
        qa.click(but_type='Pulldown', area_type=area_type, region_type='TOOLS')
        time.sleep(.5)
        if qa.find(op='MIXAR_OT_agent_model_set', popup=True)['widgets']:
            break
    qa.wait("bool(drv.find(op='MIXAR_OT_agent_model_set', popup=True))", timeout=5)
    models = qa.find(op='MIXAR_OT_agent_model_set', popup=True)['widgets']
    if len(models) != 2 or any(not w['enabled'] for w in models):
        raise ScenarioFail(f'{area_type} hosted models unavailable with no key: {models}')
    # With no key saved, Mixie's dropdown has no API-key row: adding one is
    # the island's Custom AI half (and the profile menu's AI Provider Settings).
    if qa.find(**SETTINGS)['widgets']:
        raise ScenarioFail(f'{area_type} Mixie dropdown still offers an API-key row')


def save(qa, model, name):
    qa.step(name + '_model', qa.click, op='MIXAR_BYOK_OT_pick', text=model, popup=True)
    qa.step(name + '_key', qa.cmd, 'set_text',
            widget={'prop': 'byok_form_api_key', 'popup': True},
            text='qa-synthetic-key', enter=False)
    qa.step(name + '_save', qa.click, **SAVE)
    qa.wait(f"{WM}.byok_dialog_state == 'SAVED' and {WM}.byok_is_active "
            f"and {WM}.mixar_agent_model_byok_active", timeout=10)
    qa.wait("bool(drv.find(text='Done', popup=True))", timeout=5)
    qa.click(text='Done', popup=True)
    close_popup(qa)


def remove(qa, name):
    # One click: there is no confirmation step to back out of.
    qa.step(name + '_remove', qa.click, op='MIXAR_BYOK_OT_confirm_remove', popup=True)
    qa.wait(f"{WM}.byok_dialog_state == 'REMOVED' and not {WM}.byok_is_active "
            f"and not {WM}.mixar_agent_model_byok_active", timeout=10)
    qa.wait("bool(drv.find(text='Done', popup=True))", timeout=5)
    qa.click(text='Done', popup=True)
    close_popup(qa)


def run(qa):
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.step('standalone_editor_absent', qa.eval,
            "assert not hasattr(bpy.types, 'SpaceMixieChat')\n"
            "assert 'MIXIE_CHAT' not in bpy.types.Area.bl_rna.properties['type'].enum_items.keys()\n"
            "assert 'MIXIE_CHAT' not in bpy.types.Theme.bl_rna.properties['theme_area'].enum_items.keys()\n"
            "assert all(a.type != 'MIXIE_CHAT' for w in bpy.context.window_manager.windows for a in w.screen.areas)\n"
            "km=bpy.context.window_manager.keyconfigs.addon.keymaps['Agent Chat']\n"
            "assert km.space_type == 'AGENT_BUBBLE'\n"
            "assert {'mixie_chat.select_text','mixie_chat.copy','mixie_chat.paste'} <= {i.idname for i in km.keymap_items}\n"
            "result=True")
    qa.step('install_service_fixture', qa.eval, SETUP)
    snaps = []
    try:
        snaps.append(open_profile(qa, 'initial'))
        save(qa, 'QA Model One', 'profile_save')
        qa.step('bubble_reflects_profile_save', open_picker, qa, 'AGENT_BUBBLE', True)
        qa.step('island_shared_dialog', click_key_half, qa)
        check_dialog(qa)
        qa.wait(f"{WM}.byok_current_model == 'qa-one' and {WM}.byok_form_model == 'qa-one'", timeout=5)
        snaps.append(snap(qa, 'island_sees_profile_save', {'op': 'MIXAR_BYOK_OT_pick', 'text': 'QA Model One', 'popup': True}))
        remove(qa, 'island_remove')
        snaps.append(open_profile(qa, 'after_island_remove'))
        qa.wait(f"not {WM}.byok_is_active", timeout=5)
        if qa.find(op='MIXAR_BYOK_OT_confirm_remove', popup=True)['total']:
            raise ScenarioFail('Profile still offers removal after chat removed the key')
        close_popup(qa)
        open_picker(qa, 'AGENT_BUBBLE', False)
        close_popup(qa)
        qa.step('island_custom_ai_opens_settings', click_key_half, qa)
        check_dialog(qa)
        save(qa, 'QA Model Two', 'bubble_save')
        snaps.append(open_profile(qa, 'after_bubble_save'))
        qa.wait(f"{WM}.byok_current_model == 'qa-two' and {WM}.byok_form_model == 'qa-two'", timeout=5)
        snaps.append(snap(qa, 'profile_sees_bubble_save', {'op': 'MIXAR_BYOK_OT_pick', 'text': 'QA Model Two', 'popup': True}))
        remove(qa, 'profile_remove')
        qa.step('bubble_reflects_profile_remove', open_picker, qa, 'AGENT_BUBBLE', False)
        snaps.append(snap(qa, 'agent_bubble_restored',
                          {'op': 'MIXAR_OT_agent_model_reset', 'popup': True}))
        close_popup(qa)
        counts = qa.eval("from mixar.modules.byok.ui.operators import byok_ops as O\n"
                         "f = O._qa_profile_fixture[1]\n"
                         "result = {'saves': f.saves, 'deletes': f.deletes, 'fetches': f.fetches}")
        if counts != {'saves': 2, 'deletes': 2, 'fetches': 4}:
            raise ScenarioFail(f'Unexpected service calls: {counts}')
        return {'service_calls': counts, 'snaps': snaps,
                'transport': 'synthetic service; real UI, worker threads and timers'}
    finally:
        close_popup(qa)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('profile_provider_settings_e2e', run)
