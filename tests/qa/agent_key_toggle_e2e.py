#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Island Mixie | Custom AI toggle, its key chip, and AI Provider settings.

Proves, against the real C++ toggle and chip, the real props dialog and real
clicks, every transition a user can make:
  1. no key: Mixie is the hosted model menu, Custom AI opens AI Provider
     settings (rows, OpenRouter swap, the island stepping aside);
  2. saving a key flips the toggle to Custom AI and puts the key chip after
     it, naming the provider ("OpenAI API") and the model;
  3. the chip's model pill switches the model in place (no key on the wire,
     no dialog); a rejected switch keeps the stored model and says why; with
     design-length names the provider word opens settings;
  4. Mixie with a key in use PAUSES it: no dialog, the island flips at once,
     the key chip goes, the hosted menu is live again;
  5. Custom AI with a paused key RESUMES it: no dialog, no key;
  6. a failed pause restores the toggle and raises a toast;
  7. settings opened while paused name the paused key; Use This Key resumes;
  8. Remove API Key deletes on its FIRST click; closing with the ✕ lands the
     island on Mixie with no key left.

Only the HTTP service boundary and the catalog are fixtures (shared with
profile_provider_settings_e2e); no real credentials are read or sent, and
the fixture restores the account's state on exit.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4777 \
    QA_SCENARIO_OUT=/tmp/agent-key-toggle python3 tests/qa/agent_key_toggle_e2e.py
"""

import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import ScenarioFail, run_scenario
from profile_provider_settings_e2e import (
    CLEANUP, SETUP, WM, check_dialog, close_popup, key_half, save,
)

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/agent-key-toggle'))
OUT.mkdir(parents=True, exist_ok=True)
USE_KEY = {'op': 'MIXAR_BYOK_OT_use_key', 'area_type': 'AGENT_BUBBLE'}
USE_MIXIE = {'op': 'MIXAR_BYOK_OT_use_mixie', 'area_type': 'AGENT_BUBBLE'}
CHIP_SETTINGS = {'op': 'MIXAR_BYOK_OT_open_dialog', 'area_type': 'AGENT_BUBBLE'}
PULLDOWN = {'but_type': 'Pulldown', 'area_type': 'AGENT_BUBBLE', 'region_type': 'TOOLS'}
SWITCH = {'op': 'MIXAR_BYOK_OT_switch_model', 'popup': True}
HOSTED_ROW = {'op': 'MIXAR_OT_agent_model_set', 'popup': True}
PICK = {'op': 'MIXAR_BYOK_OT_pick', 'popup': True}
REMOVE = {'op': 'MIXAR_BYOK_OT_confirm_remove', 'popup': True}
USE_THIS_KEY = {'op': 'MIXAR_BYOK_OT_use_key', 'popup': True}
CLOSE = {'text': '✕', 'popup': True}
HOST = "__import__('mixar.modules.byok.ui.operators.byok_dialog_host', fromlist=['x'])"
OPS = "__import__('mixar.modules.byok.ui.operators.byok_ops', fromlist=['x'])"
FIXTURE = f"{OPS}._qa_profile_fixture[1]"
NO_DIALOG = f"not {OPS}._dialog_open and not {HOST}._island_minimised"
TOASTS = "__import__('mixar.modules.common.notifications', fromlist=['x']).get_notification_store()"
# The fixture's models under design-length labels (same ids, so the stored
# credential stays valid); the credential mirror re-derives the chip from them.
RELABEL = """
from mixar.modules.byok.core import model_suggestions as M, credential_state as C
M.populate_from_payload({'providers': [{'id': 'openai', 'label': 'QA Provider',
    'models': [{'id': 'qa-one', 'label': 'GPT-5.5', 'platform_available': True},
               {'id': 'qa-two', 'label': 'GPT-5.4', 'platform_available': True}]}]})
C.apply_to_wm()
result = True
"""


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
    raise ScenarioFail('The click did not open AI Provider settings')


def click_until(qa, pick, condition, what):
    """Click an island control until ``condition`` holds (same focus caveat)."""
    for _ in range(2):
        click_widget(qa, pick(qa))
        time.sleep(.5)
        if qa.eval(f"result=bool({condition})"):
            return
    qa.wait(condition, timeout=5)


def island_comes_back(qa):
    """The dialog minimised the island while it was up; closing it must give
    the island back by itself, toggle and all."""
    qa.wait(f"not {HOST}._island_minimised and len(drv.find(**{USE_KEY!r})) == 1", timeout=10)


def assert_mixie_answers(qa, why):
    """Thumb on Mixie, no key chip, Mixie is the (left) hosted pulldown."""
    qa.wait(f"not {WM}.mixar_agent_model_byok_active and {WM}.mixar_agent_key_label == '' "
            f"and not drv.find(**{USE_MIXIE!r}) and len(drv.find(**{PULLDOWN!r})) == 1",
            timeout=10)
    pull, key = qa.find(**PULLDOWN)['widgets'][0], one(qa, USE_KEY, 'Custom AI half')
    if pull['rect'][0] >= key['rect'][0]:
        raise ScenarioFail(f'{why}: the hosted pulldown is not the Mixie half: {pull} {key}')


def assert_key_answers(qa, model, why):
    """Thumb on Custom AI, Mixie switches back, the chip names the model and
    its pill (the only pulldown) sits right of the toggle."""
    qa.wait(f"{WM}.mixar_agent_model_byok_active and {WM}.byok_is_active and "
            f"{WM}.mixar_agent_key_label == 'OpenAI API' and "
            f"{WM}.mixar_agent_key_model == {model!r} and len(drv.find(**{USE_MIXIE!r})) == 1 "
            f"and len(drv.find(**{PULLDOWN!r})) == 1", timeout=10)
    pill, key = qa.find(**PULLDOWN)['widgets'][0], one(qa, USE_KEY, 'Custom AI half')
    if pill['rect'][0] <= key['rect'][0]:
        raise ScenarioFail(f'{why}: the model pill is not right of the toggle: {pill} {key}')


def open_key_models(qa):
    click_until(qa, lambda qa: qa.find(**PULLDOWN)['widgets'][0],
                f"bool(drv.find(**{SWITCH!r}))", 'key models')


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
        qa.step('island_steps_aside', qa.wait, f"{HOST}._island_minimised", timeout=5)
        rows = [w['text'] for w in qa.find(**PICK)['widgets']]
        for expected in ('QA PROVIDER', 'OPENROUTER', 'CODEX (CHATGPT SUB)', 'LOCAL MODEL',
                         'QA Model One', 'QA Model Two'):
            if expected not in rows:
                raise ScenarioFail(f'{expected!r} missing from the dialog rows: {rows}')
        if rows.index('LOCAL MODEL') <= rows.index('CODEX (CHATGPT SUB)'):
            raise ScenarioFail(f'Local Model is not pinned below the providers: {rows}')
        snaps.append(snap(qa, 'provider_settings', {**PICK, 'text': 'QA PROVIDER'}))
        qa.step('pick_openrouter', qa.click, **PICK, text='OPENROUTER')
        qa.wait(f"{WM}.byok_form_provider == 'openrouter' and "
                "bool(drv.find(prop='byok_form_openrouter_model', popup=True))", timeout=5)
        if qa.find(**PICK, text='QA Model One')['widgets']:
            raise ScenarioFail('OpenRouter kept the previous provider\'s model chips')
        qa.step('pick_back', qa.click, **PICK, text='QA PROVIDER')
        qa.wait(f"{WM}.byok_form_provider == 'openai'", timeout=5)

        # 2. Save a key -> Custom AI and the key chip.
        save(qa, 'QA Model Two', 'toggle_save')
        qa.step('island_back_after_save', island_comes_back, qa)
        qa.step('key_in_use_after_save', assert_key_answers, qa, 'QA Model Two', 'after save')
        snaps.append(snap(qa, 'toggle_on_api_key', USE_KEY, margin=500))

        # 3. The chip: switch the model in place, a rejection, the full chip.
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

        qa.eval(f"{FIXTURE}.reject_next = True\nresult=True")
        qa.step('open_key_models_again', open_key_models, qa)
        qa.step('switch_rejected', qa.click, **SWITCH, text='QA Model Two')
        qa.wait(f"{TOASTS}.contains('byok_switch_model')", timeout=10)
        qa.step('rejection_keeps_model', assert_key_answers, qa, 'QA Model One', 'rejected')

        qa.eval(RELABEL)
        qa.wait(f"{WM}.mixar_agent_key_model == 'GPT-5.5' and "
                f"len(drv.find(**{CHIP_SETTINGS!r})) == 1", timeout=10)
        word = one(qa, CHIP_SETTINGS, 'provider word')
        if not one(qa, USE_KEY, 'Custom AI')['rect'][2] <= word['rect'][0] \
                <= qa.find(**PULLDOWN)['widgets'][0]['rect'][0]:
            raise ScenarioFail('Key chip order is not toggle | provider | model')
        snaps.append(snap(qa, 'key_chip_full', USE_KEY, margin=500))
        qa.step('provider_word_opens_settings', open_from_island, qa,
                lambda qa: one(qa, CHIP_SETTINGS, 'provider word'))
        check_dialog(qa)
        close_popup(qa)
        qa.step('island_back_after_provider_word', island_comes_back, qa)

        # 4. Mixie pauses the key: no dialog, the island flips, hosted menu live.
        qa.step('mixie_pauses', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.pauses == 1", 'pause')
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('paused_on_mixie', assert_mixie_answers, qa, 'paused')
        qa.wait(f"{WM}.byok_key_stored and {WM}.byok_key_paused and "
                f"{WM}.mixar_agent_key_resumable and not {FIXTURE}.enabled", timeout=5)
        snaps.append(snap(qa, 'paused_on_mixie', USE_KEY, margin=500))
        qa.step('open_hosted_menu', click_until, qa,
                lambda qa: qa.find(**PULLDOWN)['widgets'][0],
                f"bool(drv.find(**{HOSTED_ROW!r}))", 'hosted menu')
        hosted = qa.find(**HOSTED_ROW)['widgets']
        if not hosted or not all(w['enabled'] for w in hosted):
            raise ScenarioFail(f'Hosted models are not live while the key is paused: {hosted}')
        if not qa.find(text='Change or remove my API key…', popup=True)['widgets']:
            raise ScenarioFail('The hosted menu does not offer the paused key')
        # The toggle's move is in the menu too (the island fitted down to its
        # icon has no other control).
        if not qa.find(op='MIXAR_BYOK_OT_use_key', popup=True)['widgets']:
            raise ScenarioFail('The hosted menu does not offer switching back to the key')
        snaps.append(snap(qa, 'hosted_menu_while_paused', HOSTED_ROW, margin=600))
        close_popup(qa)

        # 5. Custom AI resumes the paused key: no dialog, no key.
        qa.step('custom_ai_resumes', click_until, qa, key_half,
                f"{FIXTURE}.resumes == 1", 'resume')
        qa.wait(NO_DIALOG, timeout=5)
        qa.step('resumed_on_key', assert_key_answers, qa, 'GPT-5.5', 'resumed')
        snaps.append(snap(qa, 'resumed_on_key', USE_KEY, margin=500))

        # 6. A failed pause restores the toggle and says why.
        qa.eval(f"{FIXTURE}.reject_state_next = True\nresult=True")
        qa.step('pause_rejected', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.state_rejected == 1", 'rejected pause')
        qa.wait(f"{TOASTS}.contains('byok_toggle')", timeout=10)
        qa.step('rejection_restores_key', assert_key_answers, qa, 'GPT-5.5', 'pause rejected')
        if not qa.eval(f"result={FIXTURE}.enabled"):
            raise ScenarioFail('The rejected pause changed the stored key')

        # 7. Paused, then settings from the hosted menu: the paused key is
        #    named and Use This Key resumes it.
        qa.step('pause_again', click_until, qa, lambda qa: one(qa, USE_MIXIE, 'Mixie half'),
                f"{FIXTURE}.pauses == 2", 'second pause')
        qa.step('paused_again', assert_mixie_answers, qa, 'paused again')
        qa.step('open_hosted_menu_again', click_until, qa,
                lambda qa: qa.find(**PULLDOWN)['widgets'][0],
                f"bool(drv.find(**{HOSTED_ROW!r}))", 'hosted menu')
        qa.step('settings_from_menu', qa.click, text='Change or remove my API key…', popup=True)
        check_dialog(qa)
        qa.wait("bool(drv.find(text='Paused, Mixie is answering', contains=True, popup=True))",
                timeout=5)
        qa.wait(f"bool(drv.find(**{USE_THIS_KEY!r})) and bool(drv.find(**{REMOVE!r}))", timeout=5)
        snaps.append(snap(qa, 'settings_while_paused', REMOVE))
        qa.step('use_this_key', qa.click, **USE_THIS_KEY)
        qa.wait(f"{FIXTURE}.resumes == 2 and {WM}.byok_is_active", timeout=10)
        qa.wait("bool(drv.find(text='In use:', contains=True, popup=True))", timeout=5)

        # 8. Remove API Key: first click deletes; the ✕ lands on Mixie.
        qa.step('remove_once', qa.click, **REMOVE)
        qa.wait(f"{WM}.byok_dialog_state == 'REMOVED' and not {FIXTURE}.active", timeout=10)
        qa.step('close_with_x', qa.click, **CLOSE)
        qa.wait("not bool(drv.find(popup=True))", timeout=5)
        qa.step('island_back_after_remove', island_comes_back, qa)
        qa.step('removed_on_mixie', assert_mixie_answers, qa, 'removed')
        qa.wait(f"not {WM}.byok_key_stored and not {WM}.mixar_agent_key_resumable", timeout=5)
        snaps.append(snap(qa, 'toggle_back_on_mixie', USE_KEY, margin=500))
        # With nothing stored, Custom AI is the way to add a key again.
        qa.step('custom_ai_opens_settings_again', open_from_island, qa, key_half)
        close_popup(qa)
        qa.step('island_back_at_end', island_comes_back, qa)

        counts = qa.eval(f"f = {FIXTURE}\n"
                         "result = {'saves': f.saves, 'deletes': f.deletes, "
                         "'switches': f.switches, 'rejected': f.rejected, 'pauses': f.pauses, "
                         "'resumes': f.resumes, 'state_rejected': f.state_rejected}")
        expected = {'saves': 1, 'deletes': 1, 'switches': 1, 'rejected': 1, 'pauses': 2,
                    'resumes': 2, 'state_rejected': 1}
        if counts != expected:
            raise ScenarioFail(f'Unexpected service calls: {counts}')
        return {'service_calls': counts, 'snaps': snaps,
                'transport': 'synthetic service; real UI, worker threads and timers'}
    finally:
        close_popup(qa)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_key_toggle_e2e', run)
