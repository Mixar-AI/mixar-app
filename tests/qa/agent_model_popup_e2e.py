#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""The island's model chip, its popup, and AI Provider Settings.

Proves, against the real C++ chip and popup, the real props dialog and real
clicks, every transition a user can make:
  1. no key: the chip reads Mixie; the popup opens on the Mixie tab with the
     hosted models live, and the "Add a key" tab's footer opens AI Provider
     Settings (centred in the main window, the island hidden meanwhile);
  2. saving a key moves the chip to the key ("OpenAI API" badge, the model
     name); this computer's key record remembers the model;
  3. the key tab's rows switch the model in place (the record's key is
     re-sent, no dialog, no typing); a rejected switch keeps the stored model
     and says why; the record follows a successful switch;
  4. the current Mixie row with a key in use PAUSES it: no dialog, the
     server rows go, the record stays, the chip reads Mixie, and the key tab
     offers the paused key's models;
  5. a key-tab row with a paused key RESUMES it: the record is re-sent;
  6. a failed pause leaves the key in use and raises a toast;
  7. the key tab's "Manage key…" while paused opens the settings sheet, whose
     line says "Paused, Mixie is answering" and names the key; "Use my key"
     resumes it from there;
  8. Remove key (two clicks) deletes the rows AND the record; the chip lands
     on Mixie and the key tab is "Add a key" again.

Only the HTTP service boundary, the transport sealer and the catalog are
fixtures (shared with profile_provider_settings_e2e); the key record written
to this computer's credential store is the fixture's and the account's real
record, if any, is restored on exit. No real credentials are read or sent.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \\
    QA_SCENARIO_OUT=/tmp/agent-model-popup python3 tests/qa/agent_model_popup_e2e.py
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
import model_popup as mp  # noqa: E402

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/agent-model-popup'))
OUT.mkdir(parents=True, exist_ok=True)
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


def open_settings_from_tab(qa, tab_id, text):
    """Open AI Provider Settings from the card: "Add a key" is one click on
    the tab itself; otherwise the tab's footer row (``text``)."""
    if text == 'Add a key…':
        mp.open_settings(qa)
    else:
        mp.show_tab(qa, tab_id)
        mp.settings(qa, text)
    qa.wait(f"{OPS}._dialog_open", timeout=5)


def island_comes_back(qa):
    """The modal dialog hid the island while it was up; closing it must give
    the island back by itself, chip and all."""
    qa.wait(f"{NO_DIALOG} and len(drv.find(**{mp.CHIP!r})) == 1", timeout=10)


def assert_mixie_answers(qa, why):
    qa.wait(f"not {WM}.mixar_agent_model_byok_active and {WM}.mixar_agent_source == 'MIXIE' "
            f"and {WM}.mixar_agent_source_state == 'OK'", timeout=10)
    if mp.chip(qa)[1] != 'Mixie':
        raise ScenarioFail(f'{why}: the chip badge is not Mixie: {mp.chip(qa)}')


def assert_key_answers(qa, model, why):
    qa.wait(f"{WM}.mixar_agent_model_byok_active and {WM}.byok_is_active and "
            f"{WM}.mixar_agent_source == 'KEY' and {WM}.mixar_agent_source_state == 'OK'",
            timeout=10)
    if mp.chip(qa) != ('KEY', 'OpenAI API', model, 'OK'):
        raise ScenarioFail(f'{why}: the chip does not name the key and {model}: {mp.chip(qa)}')


def assert_record(qa, model, why):
    """This computer's key record names ``model`` (None: no record)."""
    record = qa.eval(f"r = {RECORD}\nresult = None if r is None else r.get('model')")
    if record != model:
        raise ScenarioFail(f'{why}: the key record on this computer says {record!r}, '
                           f'expected {model!r}')


def pick_and_wait(qa, text, condition, contains=False):
    qa.step('pick_' + text.replace(' ', '_').lower(), mp.pick, qa, text, contains)
    qa.wait(condition, timeout=10)
    qa.wait("not bool(drv.find(popup=True))", timeout=5)


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
        # 1. No key: Mixie answers, hosted rows live, the key tab adds a key.
        qa.step('no_key_on_mixie', assert_mixie_answers, qa, 'no key')
        qa.step('open_popup', mp.open_popup, qa)
        if mp.open_tab(qa) != 'MIXIE':
            raise ScenarioFail(f'The popup did not open on Mixie: {mp.open_tab(qa)}')
        hosted = mp.rows(qa)
        if not hosted or not all(enabled for _, enabled in hosted):
            raise ScenarioFail(f'Hosted models are not live without a key: {hosted}')
        snaps.append(snap(qa, 'popup_on_mixie', mp.PICK, margin=600))
        qa.step('open_settings', open_settings_from_tab, qa, 'KEY', 'Add a key…')
        check_dialog(qa)
        snaps.append(snap(qa, 'provider_settings', {'op': 'MIXAR_BYOK_OT_save', 'popup': True}))
        close_popup(qa)
        qa.step('island_back_after_cancel', island_comes_back, qa)

        # 2. Save a key -> the chip names it; the record remembers the model.
        qa.step('open_settings_to_save', open_settings_from_tab, qa, 'KEY', 'Add a key…')
        check_dialog(qa)
        save(qa, 'QA Model Two', 'popup_save')
        qa.step('island_back_after_save', island_comes_back, qa)
        qa.step('key_in_use_after_save', assert_key_answers, qa, 'QA Model Two', 'after save')
        qa.step('record_after_save', assert_record, qa, 'qa-two', 'after save')
        snaps.append(snap(qa, 'chip_on_key', mp.CHIP, margin=500))

        # 3. The key tab: switch the model in place, then a rejection.
        qa.step('open_key_tab', mp.show_tab, qa, 'KEY')
        if [t for t, _ in mp.rows(qa)] != ['QA Model One', 'QA Model Two']:
            raise ScenarioFail(f'The key tab does not list the provider models: {mp.rows(qa)}')
        snaps.append(snap(qa, 'popup_key_tab', mp.PICK, margin=600))
        pick_and_wait(qa, 'QA Model One',
                      f"{WM}.byok_current_model == 'qa-one' and {WM}.mixar_agent_source_state == 'OK' "
                      f"and {NO_DIALOG}")
        qa.step('switched_in_place', assert_key_answers, qa, 'QA Model One', 'after switch')
        qa.step('record_follows_switch', assert_record, qa, 'qa-one', 'after switch')

        qa.eval(f"{FIXTURE}.reject_next = True\nresult=True")
        qa.step('open_key_tab_again', mp.show_tab, qa, 'KEY')
        pick_and_wait(qa, 'QA Model Two', f"{TOASTS}.contains('byok_switch_model')")
        qa.step('rejection_keeps_model', assert_key_answers, qa, 'QA Model One', 'rejected')
        qa.step('record_keeps_model', assert_record, qa, 'qa-one', 'rejected switch')

        # 4. The current Mixie row pauses the key: rows gone, record kept.
        qa.step('open_mixie_tab', mp.show_tab, qa, 'MIXIE')
        pick_and_wait(qa, 'Mixar default', f"{FIXTURE}.deletes == 1")
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('paused_on_mixie', assert_mixie_answers, qa, 'paused')
        qa.wait(f"{WM}.byok_key_resumable and not {FIXTURE}.active", timeout=5)
        qa.step('record_kept_on_pause', assert_record, qa, 'qa-one', 'paused')
        snaps.append(snap(qa, 'chip_paused_on_mixie', mp.CHIP, margin=500))
        qa.step('paused_key_tab', mp.show_tab, qa, 'KEY')
        paused = mp.rows(qa)
        if not paused or not all(enabled for _, enabled in paused):
            raise ScenarioFail(f'The paused key is not offered back: {paused}')
        snaps.append(snap(qa, 'popup_paused_key_tab', mp.PICK, margin=600))

        # 5. A key-tab row resumes the paused key: the record is re-sent.
        pick_and_wait(qa, 'QA Model One', f"len({FIXTURE}.puts) == 4", contains=True)
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('resumed_on_key', assert_key_answers, qa, 'QA Model One', 'resumed')

        # 6. A failed pause leaves the key in use and says why.
        qa.eval(f"{FIXTURE}.reject_delete_next = True\nresult=True")
        qa.step('open_mixie_tab_again', mp.show_tab, qa, 'MIXIE')
        pick_and_wait(qa, 'Mixar default', f"{FIXTURE}.delete_rejected == 1")
        qa.wait(f"{TOASTS}.contains('byok_toggle')", timeout=10)
        qa.step('rejection_keeps_key', assert_key_answers, qa, 'QA Model One', 'pause rejected')
        if not qa.eval(f"result={FIXTURE}.active"):
            raise ScenarioFail('The rejected pause changed the server state')

        # 7. Paused, then Manage key…: "Paused", the key named, Use my key resumes.
        qa.step('open_mixie_tab_to_pause', mp.show_tab, qa, 'MIXIE')
        pick_and_wait(qa, 'Mixar default', f"{FIXTURE}.deletes == 2")
        qa.step('paused_again', assert_mixie_answers, qa, 'paused again')
        qa.wait(f"{WM}.byok_key_resumable", timeout=5)
        qa.step('manage_paused_key', open_settings_from_tab, qa, 'KEY', 'Manage key…')
        check_dialog(qa)
        qa.wait("bool(drv.find(text='Paused, Mixie is answering', contains=True, popup=True))",
                timeout=5)
        qa.wait(f"bool(drv.find(**{USE_MY_KEY!r})) and bool(drv.find(**{FORGET!r}))", timeout=5)
        if qa.eval(f"result={WM}.byok_form_provider") != 'openai':
            raise ScenarioFail('The paused key did not prefill the form')
        snaps.append(snap(qa, 'settings_while_paused', USE_MY_KEY))
        qa.step('use_my_key', qa.click, **USE_MY_KEY)
        qa.wait(f"len({FIXTURE}.puts) == 5 and {WM}.byok_is_active", timeout=10)
        qa.wait("bool(drv.find(text='In use:', contains=True, popup=True))", timeout=5)

        # 8. Remove key: two clicks delete the rows and the record.
        remove(qa, 'remove')
        qa.step('island_back_after_remove', island_comes_back, qa)
        qa.step('removed_on_mixie', assert_mixie_answers, qa, 'removed')
        qa.wait(f"not {WM}.byok_key_resumable", timeout=5)
        qa.step('record_gone_after_remove', assert_record, qa, None, 'removed')
        qa.step('add_a_key_again', open_settings_from_tab, qa, 'KEY', 'Add a key…')
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
        mp.close_popup(qa)
        close_popup(qa)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_popup_e2e', run)
