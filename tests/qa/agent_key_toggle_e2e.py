#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""Island Mixie | Custom AI toggle, its key chip, and AI Provider Settings.

Proves, against the real C++ toggle and chip, the real props dialog and real
clicks, every transition a user can make:
  1. no key: Mixie is the hosted model menu, Custom AI opens AI Provider
     Settings (centred in the main window, the island hidden meanwhile);
  2. saving a key flips the toggle to Custom AI and puts the key chip after
     it, naming the provider ("OpenAI API") and the model; this computer's
     key record remembers the model;
  3. the chip's model pill switches the model in place (the record's key is
     re-sent, no dialog, no typing); a rejected switch keeps the stored model
     and says why; the record follows a successful switch;
  4. Mixie with a key in use PAUSES it: no dialog, the server rows go, the
     record stays, the key chip goes, the hosted menu is live again and
     carries "Switch back to my API key";
  5. Custom AI with a paused key RESUMES it: the record is re-sent, no dialog;
  6. a failed pause leaves the key in use and raises a toast;
  7. settings opened while paused say "Paused", name the key, and "Use my
     key" resumes it from there;
  8. Remove key (two clicks) deletes the rows AND the record; the island
     lands on Mixie with nothing to resume.

Only the HTTP service boundary, the transport sealer and the catalog are
fixtures (shared with profile_provider_settings_e2e); the key record written
to this computer's credential store is the fixture's and the account's real
record, if any, is restored on exit. No real credentials are read or sent.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \\
    QA_SCENARIO_OUT=/tmp/agent-key-toggle python3 tests/qa/agent_key_toggle_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ScenarioFail, run_scenario  # noqa: E402
from profile_provider_settings_e2e import (  # noqa: E402
    CLEANUP as PROFILE_CLEANUP, SETUP as PROFILE_SETUP, WM, check_dialog, close_popup,
    remove, save,
)

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/agent-key-toggle'))
OUT.mkdir(parents=True, exist_ok=True)
USE_KEY = {'op': 'MIXAR_BYOK_OT_use_key', 'area_type': 'AGENT_BUBBLE'}
USE_MIXIE = {'op': 'MIXAR_BYOK_OT_use_mixie', 'area_type': 'AGENT_BUBBLE'}
CHIP_SETTINGS = {'op': 'MIXAR_BYOK_OT_open_dialog', 'area_type': 'AGENT_BUBBLE'}
PULLDOWN = {'but_type': 'Pulldown', 'area_type': 'AGENT_BUBBLE', 'region_type': 'TOOLS'}
SWITCH = {'op': 'MIXAR_BYOK_OT_switch_model', 'popup': True}
HOSTED_ROW = {'op': 'MIXAR_OT_agent_model_set', 'popup': True}
USE_MY_KEY = {'op': 'MIXAR_BYOK_OT_use_key', 'popup': True}
FORGET = {'op': 'MIXAR_BYOK_OT_forget_stored_key', 'popup': True}
OPS = "__import__('mixar.modules.byok.ui.operators.byok_ops', fromlist=['x'])"
FIXTURE = f"{OPS}._qa_profile_fixture[1]"
NO_DIALOG = f"not {OPS}._dialog_open"
TOASTS = "__import__('mixar.modules.common.notifications', fromlist=['x']).get_notification_store()"
RECORD = "__import__('mixar.modules.byok.core.key_store', fromlist=['x']).load()"

# On top of the profile fixture: the sealer is bypassed (the fake service
# has no transport key), the PUT may be rejected on demand, every PUT and
# DELETE is counted with the model it carried, and this computer's real key
# record is saved for CLEANUP.
SETUP = PROFILE_SETUP + """
from mixar.modules.byok.core import transport_seal as T, key_store as K
from mixar.modules.byok.ui.operators import byok_ops as O
saved, fixture = O._qa_profile_fixture
fixture.puts, fixture.rejected, fixture.reject_next = [], 0, False
fixture.reject_delete_next, fixture.delete_rejected = False, 0
class _Rejected(Exception):
    status_code, message = 400, 'Model not available: QA rejected it'
_save = service.save_credentials_all
def save_or_reject(**kwargs):
    fixture.puts.append(kwargs['model'])
    if fixture.reject_next:
        fixture.reject_next = False
        fixture.rejected += 1
        raise _Rejected()
    return _save(**kwargs)
_delete = service.delete_credentials_all
def delete_or_reject():
    if fixture.reject_delete_next:
        fixture.reject_delete_next = False
        fixture.delete_rejected += 1
        raise _Rejected()
    return _delete()
service.save_credentials_all = save_or_reject
service.delete_credentials_all = delete_or_reject
O._qa_profile_fixture = (saved + (T.seal, K.load()), fixture)
T.seal = lambda secret: secret
result = True
"""

CLEANUP = """
from mixar.modules.byok.core import transport_seal as T, key_store as K
from mixar.modules.byok.ui.operators import byok_ops as O
saved, fixture = O._qa_profile_fixture
T.seal = saved[-2]
if saved[-1] is not None:
    K.save(saved[-1])
else:
    K.delete()
O._qa_profile_fixture = (saved[:-2], fixture)
""" + PROFILE_CLEANUP


def snap(qa, name, target, margin=1500):
    """Flush the target's window, then snap it (popups and the island glass
    otherwise present their preceding frame)."""
    qa.eval(f"widget=drv.find_one(**{target!r})\n"
            "win=widget['_win']\n"
            "with bpy.context.temp_override(window=win, area=next(iter(win.screen.areas))):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(.6)  # the thumb slides on the shared Zen timing
    path = str(OUT / (name + '.png'))
    qa.step(name + '_snap', qa.cmd, 'snap', path=path, target=target, margin=margin)
    return path


def click_widget(qa, widget):
    qa.cmd('click_xy', x=widget['center'][0], y=widget['center'][1], window=widget['window'])


def one(qa, target, what):
    widgets = qa.find(**target)['widgets']
    if len(widgets) != 1:
        raise ScenarioFail(f'Expected one {what}: {widgets}')
    return widgets[0]


def key_half(qa):
    return one(qa, USE_KEY, 'Custom AI half')


def open_from_island(qa, pick):
    """Click until the dialog is up. The first native click after the island
    reopens can commit its composer focus instead (see
    agent_model_chip_label_e2e.open_picker): retry once, only when the dialog
    demonstrably stayed shut."""
    for _ in range(2):
        click_widget(qa, pick(qa))
        time.sleep(.4)
        if qa.eval(f"result={OPS}._dialog_open"):
            return
    raise ScenarioFail('The click did not open AI Provider Settings')


def click_until(qa, pick, condition, what):
    """Click an island control until ``condition`` holds (same focus caveat)."""
    for _ in range(2):
        click_widget(qa, pick(qa))
        time.sleep(.5)
        if qa.eval(f"result=bool({condition})"):
            return
    qa.wait(condition, timeout=5)


def island_comes_back(qa):
    """The modal dialog hid the island while it was up; closing it must give
    the island back by itself, toggle and all."""
    qa.wait(f"{NO_DIALOG} and len(drv.find(**{USE_KEY!r})) == 1", timeout=10)


def assert_mixie_answers(qa, why):
    """Thumb on Mixie, no key chip, Mixie is the (left) hosted pulldown."""
    qa.wait(f"not {WM}.mixar_agent_model_byok_active and {WM}.mixar_agent_key_label == '' "
            f"and not drv.find(**{USE_MIXIE!r}) and len(drv.find(**{PULLDOWN!r})) == 1",
            timeout=10)
    pull, key = qa.find(**PULLDOWN)['widgets'][0], key_half(qa)
    if pull['rect'][0] >= key['rect'][0]:
        raise ScenarioFail(f'{why}: the hosted pulldown is not the Mixie half: {pull} {key}')


def assert_key_answers(qa, model, why):
    """Thumb on Custom AI, Mixie switches back, the chip names the model and
    its pill (the only pulldown) sits right of the toggle."""
    qa.wait(f"{WM}.mixar_agent_model_byok_active and {WM}.byok_is_active and "
            f"{WM}.mixar_agent_key_label == 'OpenAI API' and "
            f"{WM}.mixar_agent_key_model == {model!r} and not {WM}.mixar_agent_key_busy and "
            f"len(drv.find(**{USE_MIXIE!r})) == 1 and len(drv.find(**{PULLDOWN!r})) == 1",
            timeout=10)
    pill, key = qa.find(**PULLDOWN)['widgets'][0], key_half(qa)
    if pill['rect'][0] <= key['rect'][0]:
        raise ScenarioFail(f'{why}: the model pill is not right of the toggle: {pill} {key}')


def assert_record(qa, model, why):
    """This computer's key record names ``model`` (None: no record)."""
    record = qa.eval(f"r = {RECORD}\nresult = None if r is None else r.get('model')")
    if record != model:
        raise ScenarioFail(f'{why}: the key record on this computer says {record!r}, '
                           f'expected {model!r}')


def open_key_models(qa):
    click_until(qa, lambda qa: qa.find(**PULLDOWN)['widgets'][0],
                f"bool(drv.find(**{SWITCH!r}))", 'key models')


def open_hosted_menu(qa):
    click_until(qa, lambda qa: qa.find(**PULLDOWN)['widgets'][0],
                f"bool(drv.find(**{HOSTED_ROW!r}))", 'hosted menu')


def run(qa):
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    # Let the login-time catalog fetch land first, or it replaces the
    # fixture's catalog mid-scenario.
    qa.step('login_catalog_loaded', qa.wait,
            "__import__('mixar.modules.byok.core.model_suggestions', "
            "fromlist=['x']).is_loaded()", timeout=30)
    qa.step('install_service_fixture', qa.eval, SETUP)
    snaps = []
    try:
        # 1. No key: Mixie = hosted menu, Custom AI = settings.
        qa.step('no_key_on_mixie', assert_mixie_answers, qa, 'no key')
        snaps.append(snap(qa, 'toggle_on_mixie', USE_KEY, margin=500))
        qa.step('open_settings', open_from_island, qa, key_half)
        check_dialog(qa)
        snaps.append(snap(qa, 'provider_settings', {'op': 'MIXAR_BYOK_OT_save', 'popup': True}))
        close_popup(qa)
        qa.step('island_back_after_cancel', island_comes_back, qa)

        # 2. Save a key -> Custom AI and the key chip; the record remembers the model.
        qa.step('open_settings_to_save', open_from_island, qa, key_half)
        check_dialog(qa)
        save(qa, 'QA Model Two', 'toggle_save')
        qa.step('island_back_after_save', island_comes_back, qa)
        qa.step('key_in_use_after_save', assert_key_answers, qa, 'QA Model Two', 'after save')
        qa.step('record_after_save', assert_record, qa, 'qa-two', 'after save')
        snaps.append(snap(qa, 'toggle_on_api_key', USE_KEY, margin=500))

        # 3. The chip: switch the model in place, then a rejection.
        qa.step('open_key_models', open_key_models, qa)
        rows = [w['text'] for w in qa.find(**SWITCH)['widgets']]
        if rows != ['QA Model One', 'QA Model Two']:
            raise ScenarioFail(f'The key dropdown does not list the provider models: {rows}')
        snaps.append(snap(qa, 'key_model_menu', {**SWITCH, 'text': 'QA Model One'}, margin=600))
        qa.step('switch_to_model_one', qa.click, **SWITCH, text='QA Model One')
        qa.wait(f"{WM}.byok_current_model == 'qa-one' and not {WM}.mixar_agent_key_busy and "
                f"{NO_DIALOG}", timeout=10)
        qa.wait("not bool(drv.find(popup=True))", timeout=5)
        qa.step('switched_in_place', assert_key_answers, qa, 'QA Model One', 'after switch')
        qa.step('record_follows_switch', assert_record, qa, 'qa-one', 'after switch')

        qa.eval(f"{FIXTURE}.reject_next = True\nresult=True")
        qa.step('open_key_models_again', open_key_models, qa)
        qa.step('switch_rejected', qa.click, **SWITCH, text='QA Model Two')
        qa.wait(f"{TOASTS}.contains('byok_switch_model')", timeout=10)
        qa.step('rejection_keeps_model', assert_key_answers, qa, 'QA Model One', 'rejected')
        qa.step('record_keeps_model', assert_record, qa, 'qa-one', 'rejected switch')

        # 4. Mixie pauses the key: rows gone, record kept, hosted menu live.
        qa.step('mixie_pauses', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.deletes == 1", 'pause')
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('paused_on_mixie', assert_mixie_answers, qa, 'paused')
        qa.wait(f"{WM}.byok_key_resumable and {WM}.mixar_agent_key_resumable and "
                f"not {FIXTURE}.active", timeout=5)
        qa.step('record_kept_on_pause', assert_record, qa, 'qa-one', 'paused')
        snaps.append(snap(qa, 'paused_on_mixie', USE_KEY, margin=500))
        qa.step('open_hosted_menu', open_hosted_menu, qa)
        hosted = qa.find(**HOSTED_ROW)['widgets']
        if not hosted or not all(w['enabled'] for w in hosted):
            raise ScenarioFail(f'Hosted models are not live while the key is paused: {hosted}')
        if not qa.find(text='Change or remove my API key…', popup=True)['widgets']:
            raise ScenarioFail('The hosted menu does not offer the paused key')
        # The toggle's move is in the menu too (the island fitted down to its
        # icon has no other control).
        if not qa.find(**USE_MY_KEY)['widgets']:
            raise ScenarioFail('The hosted menu does not offer switching back to the key')
        snaps.append(snap(qa, 'hosted_menu_while_paused', HOSTED_ROW, margin=600))
        close_popup(qa)

        # 5. Custom AI resumes the paused key: the record is re-sent, no dialog.
        qa.step('custom_ai_resumes', click_until, qa, key_half,
                f"len({FIXTURE}.puts) == 4", 'resume')
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('resumed_on_key', assert_key_answers, qa, 'QA Model One', 'resumed')
        snaps.append(snap(qa, 'resumed_on_key', USE_KEY, margin=500))

        # 6. A failed pause leaves the key in use and says why.
        qa.eval(f"{FIXTURE}.reject_delete_next = True\nresult=True")
        qa.step('pause_rejected', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.delete_rejected == 1", 'rejected pause')
        qa.wait(f"{TOASTS}.contains('byok_toggle')", timeout=10)
        qa.step('rejection_keeps_key', assert_key_answers, qa, 'QA Model One', 'pause rejected')
        if not qa.eval(f"result={FIXTURE}.active"):
            raise ScenarioFail('The rejected pause changed the server state')

        # 7. Paused, then settings from the hosted menu: "Paused", the key
        #    named, and Use my key resumes it from the dialog.
        qa.step('pause_again', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.deletes == 2", 'second pause')
        qa.step('paused_again', assert_mixie_answers, qa, 'paused again')
        qa.wait(f"{WM}.byok_key_resumable", timeout=5)
        qa.step('open_hosted_menu_again', open_hosted_menu, qa)
        qa.step('settings_from_menu', qa.click, text='Change or remove my API key…', popup=True)
        check_dialog(qa)
        qa.wait("bool(drv.find(text='Paused', popup=True)) and "
                "bool(drv.find(text='Your key is paused', contains=True, popup=True))", timeout=5)
        qa.wait(f"bool(drv.find(**{USE_MY_KEY!r})) and bool(drv.find(**{FORGET!r}))", timeout=5)
        if qa.eval(f"result={WM}.byok_form_provider") != 'openai':
            raise ScenarioFail('The paused key did not prefill the form')
        snaps.append(snap(qa, 'settings_while_paused', USE_MY_KEY))
        qa.step('use_my_key', qa.click, **USE_MY_KEY)
        qa.wait(f"len({FIXTURE}.puts) == 5 and {WM}.byok_is_active", timeout=10)
        qa.wait("bool(drv.find(text='Current Configuration', popup=True))", timeout=5)

        # 8. Remove key: two clicks delete the rows and the record.
        remove(qa, 'remove')
        qa.step('island_back_after_remove', island_comes_back, qa)
        qa.step('removed_on_mixie', assert_mixie_answers, qa, 'removed')
        qa.wait(f"not {WM}.byok_key_resumable and not {WM}.mixar_agent_key_resumable", timeout=5)
        qa.step('record_gone_after_remove', assert_record, qa, None, 'removed')
        snaps.append(snap(qa, 'toggle_back_on_mixie', USE_KEY, margin=500))
        # With nothing saved, Custom AI is the way to add a key again.
        qa.step('custom_ai_opens_settings_again', open_from_island, qa, key_half)
        close_popup(qa)
        qa.step('island_back_at_end', island_comes_back, qa)

        counts = qa.eval(f"f = {FIXTURE}\n"
                         "result = {'puts': list(f.puts), 'deletes': f.deletes, "
                         "'rejected': f.rejected, 'delete_rejected': f.delete_rejected}")
        expected = {'puts': ['qa-two', 'qa-one', 'qa-two', 'qa-one', 'qa-one'], 'deletes': 3,
                    'rejected': 1, 'delete_rejected': 1}
        if counts != expected:
            raise ScenarioFail(f'Unexpected service calls: {counts}')
        return {'service_calls': counts, 'snaps': snaps,
                'transport': 'synthetic service; real UI, worker threads, timers and key store'}
    finally:
        close_popup(qa)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_key_toggle_e2e', run)
