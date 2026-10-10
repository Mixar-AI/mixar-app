#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Island Mixie | Custom AI toggle and the two-column AI Provider settings.

Proves, against the real C++ toggle, the real props dialog and real clicks:
  1. with no key the toggle sits on Mixie: the left half is the hosted model
     menu, the right half opens AI Provider settings;
  2. the dialog lists every provider as a row (Local Model last) and every
     model of the selected provider as a chip; switching provider swaps the
     right column (OpenRouter -> its free-text model field);
  3. the island steps aside to its pill while the centred dialog is up and
     comes back by itself when it closes;
  4. saving a key flips the toggle to the key's side, which then names the
     provider instead of "Custom AI" (Mixie becomes `use_mixie`, the hosted
     menu is withdrawn);
  5. Mixie with a key in use opens straight on the remove confirmation;
     Keep My Key backs out with the key intact, Remove returns to Mixie.

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
HALVES = {'op': 'MIXAR_BYOK_OT_open_dialog', 'area_type': 'AGENT_BUBBLE'}
USE_MIXIE = {'op': 'MIXAR_BYOK_OT_use_mixie', 'area_type': 'AGENT_BUBBLE'}
MIXIE_MENU = {'but_type': 'Pulldown', 'area_type': 'AGENT_BUBBLE', 'region_type': 'TOOLS'}
PICK = {'op': 'MIXAR_BYOK_OT_pick', 'popup': True}


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


def open_from_island(qa, pick_half):
    """Click a toggle half until the dialog is up. The first native click
    after the island reopens can commit its composer focus instead (see
    agent_model_chip_label_e2e.open_picker): retry once, only when the
    dialog demonstrably stayed shut."""
    for _ in range(2):
        click_widget(qa, pick_half(qa))
        time.sleep(.4)
        if qa.eval("from mixar.modules.byok.ui.operators import byok_ops as O\n"
                   "result=O._dialog_open"):
            return
    raise ScenarioFail('The toggle half did not open AI Provider settings')


HOST = "__import__('mixar.modules.byok.ui.operators.byok_dialog_host', fromlist=['x'])"


def island_comes_back(qa):
    """The dialog minimised the island while it was up; closing it must give
    the island back by itself, toggle and all."""
    qa.wait(f"not {HOST}._island_minimised and len(drv.find(**{HALVES!r})) >= 1", timeout=10)


def mixie_half_with_key(qa):
    halves = qa.find(**USE_MIXIE)['widgets']
    if len(halves) != 1:
        raise ScenarioFail(f'Expected the Mixie half to offer switching back: {halves}')
    key = qa.find(**HALVES)['widgets']
    if len(key) != 1 or key[0]['rect'][0] <= halves[0]['rect'][0]:
        raise ScenarioFail(f'Mixie half is not left of the key half: {halves} {key}')
    return halves[0]


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
        # 1. No key: Mixie half = hosted menu, API key half = settings.
        qa.wait(f"not {WM}.mixar_agent_model_byok_active", timeout=5)
        qa.wait(f"len(drv.find(**{HALVES!r})) == 1 and len(drv.find(**{MIXIE_MENU!r})) == 1",
                timeout=10)
        snaps.append(snap(qa, 'toggle_on_mixie', HALVES, margin=500))

        # 2. API key -> two-column settings in the main window.
        qa.step('open_settings', open_from_island, qa, key_half)
        check_dialog(qa)
        # The island is an always-on-top window: it steps aside to its pill
        # so the (centred) dialog is not drawn underneath it.
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
        snaps.append(snap(qa, 'provider_openrouter', {**PICK, 'text': 'OPENROUTER'}))
        qa.step('pick_back', qa.click, **PICK, text='QA PROVIDER')
        qa.wait(f"{WM}.byok_form_provider == 'openai'", timeout=5)

        # 3. Save a key -> the toggle moves to API key.
        save(qa, 'QA Model Two', 'toggle_save')
        qa.wait(f"{WM}.mixar_agent_model_byok_active", timeout=10)
        qa.step('island_back_after_save', island_comes_back, qa)
        qa.step('key_half_names_provider', qa.wait,
                f"{WM}.mixar_agent_key_label == 'QA Provider'", timeout=5)
        qa.wait(f"len(drv.find(**{HALVES!r})) == 1 and len(drv.find(**{USE_MIXIE!r})) == 1 "
                f"and not drv.find(**{MIXIE_MENU!r})", timeout=10)
        snaps.append(snap(qa, 'toggle_on_api_key', HALVES, margin=500))

        # 4a. Mixie with a key -> remove confirmation; Keep My Key backs out.
        qa.step('mixie_keep', open_from_island, qa, mixie_half_with_key)
        qa.wait(f"{WM}.byok_dialog_state == 'CONFIRM_REMOVE'", timeout=10)
        qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_confirm_remove', popup=True))", timeout=5)
        snaps.append(snap(qa, 'switch_to_mixie_confirm',
                          {'op': 'MIXAR_BYOK_OT_confirm_remove', 'popup': True}))
        qa.step('keep_key', qa.click, op='MIXAR_BYOK_OT_cancel_remove', popup=True)
        qa.wait(f"{WM}.byok_dialog_state == 'IDLE' and {WM}.byok_is_active", timeout=5)
        close_popup(qa)
        qa.step('island_back_after_keep', island_comes_back, qa)

        # 4b. Mixie again -> Remove -> back on Mixie.
        qa.step('mixie_remove', open_from_island, qa, mixie_half_with_key)
        qa.wait(f"{WM}.byok_dialog_state == 'CONFIRM_REMOVE'", timeout=10)
        qa.step('confirm_remove', qa.click, op='MIXAR_BYOK_OT_confirm_remove', popup=True)
        qa.wait(f"{WM}.byok_dialog_state == 'REMOVED' and not {WM}.byok_is_active "
                f"and not {WM}.mixar_agent_model_byok_active", timeout=10)
        qa.wait("bool(drv.find(text='Done', popup=True))", timeout=5)
        qa.click(text='Done', popup=True)
        close_popup(qa)
        qa.step('island_back_after_remove', island_comes_back, qa)
        qa.step('key_half_reads_api_key', qa.wait, f"{WM}.mixar_agent_key_label == ''", timeout=5)
        qa.wait(f"len(drv.find(**{MIXIE_MENU!r})) == 1", timeout=10)
        snaps.append(snap(qa, 'toggle_back_on_mixie', HALVES, margin=500))

        counts = qa.eval("from mixar.modules.byok.ui.operators import byok_ops as O\n"
                         "f = O._qa_profile_fixture[1]\n"
                         "result = {'saves': f.saves, 'deletes': f.deletes}")
        if counts != {'saves': 1, 'deletes': 1}:
            raise ScenarioFail(f'Unexpected service calls: {counts}')
        return {'service_calls': counts, 'snaps': snaps,
                'transport': 'synthetic service; real UI, worker threads and timers'}
    finally:
        close_popup(qa)
        qa.step('restore_service_and_state', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_key_toggle_e2e', run)
