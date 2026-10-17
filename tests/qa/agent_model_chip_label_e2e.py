#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Island model chip label + the key tab; no credits, credentials or writes.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4811 \
  QA_SCENARIO_OUT=/tmp/chip-label python3 tests/qa/agent_model_chip_label_e2e.py
Run in an isolated QA app. Inspect the saved PNGs as well as the state verdict.

Proves, against the real C++ chip and the real native popup:
  1. a hosted pick WITH a thinking level draws the "Mixie" badge and
     `<model> · <Level>` on the chip; the popup's Mixie tab lights the pick
     and its "Thinking: High" disclosure opens the levels in place;
  2. a user key moves the chip to the key (its provider's badge, its model),
     even when the credential state lands AFTER the preference mirror;
  3. the card opens on the key tab with the key's model (one the catalog
     does not list still gets its row), greyed with "Key needed on this
     computer" and "Enter key…" while the key is not on this computer.
Only the preference service and the credential mirror are synthetic (memory
only — `credential_state` never touches the keychain, and the fixture restores
the account's real mirror on exit). No PUT/DELETE reaches the backend.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib import run_scenario
import model_popup as mp

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chip-label'))
OUT.mkdir(parents=True, exist_ok=True)
PICKER = mp.CHIP
CHIP_WITH_LEVEL = 'QA Model · High'
SETUP = """
import bpy, os
from types import SimpleNamespace
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import credential_state as C, catalog_labels as L
from mixar.modules.byok.core import model_suggestions as M
assert os.environ.get('MIXAR_QA') == '1'
assert not P.mutation_pending()
cred = C.snapshot()
saved = (F.get_agent_service, M.get_platform_models, P.snapshot(),
         bpy.context.preferences.view.show_tooltips,
         L.lookup_provider_label, L.lookup_model_label, cred)
f = SimpleNamespace(items=[], puts=0, deletes=0)
f.records = [dict(provider_id='qa-provider', provider_label='Hidden Provider',
    model_id='qa-model', model_label='QA Model', eligible=True,
    thinking_levels=['low', 'high'])]
M.get_platform_models = lambda: f.records
response = lambda data: SimpleNamespace(success=True, status_code=200, data={'data': data})
service = SimpleNamespace(get_model_preference=lambda: response({'items': f.items}),
                          put_model_preference=lambda **k: response({}),
                          delete_model_preference=lambda role: response({'removed': 0}))
F.get_agent_service = lambda: service
# Mixie answers first: the account's own key (if any) is set aside in memory.
C.apply_from_payload({'byok_active': False, 'items': []}, bpy.context.window_manager)
labels = {'qa-key-provider': 'QA Key Provider', 'qa-key-model': 'QA Key Model'}
L.lookup_provider_label = lambda pid: labels.get(pid, pid)
L.lookup_model_label = lambda pid, mid: labels.get(mid, mid)
P.clear()
P.apply_from_payload({'items': [dict(role='default', provider='qa-provider',
    model='qa-model', label='Hidden Provider · QA Model', thinking_level='high')],
    'byok_active': False})
P._qa_chip_label = (saved, f)
bpy.context.preferences.view.show_tooltips = False
P._redraw()
result = True
"""
CLEANUP = """
from mixar.modules.byok.core import preference_client as F, preference_state as P
from mixar.modules.byok.core import credential_state as C, catalog_labels as L
from mixar.modules.byok.core import model_suggestions as M
saved, f = P._qa_chip_label
cred = saved[6]
P.clear()
F.get_agent_service, M.get_platform_models = saved[:2]
L.lookup_provider_label, L.lookup_model_label = saved[4], saved[5]
# Round-trip the account's real credential mirror back through the parser.
C.apply_from_payload({'byok_active': cred['byok_is_active'], 'items': [dict(
    provider=cred['byok_current_provider'], model=cred['byok_current_model'],
    supports_vision=cred['byok_current_supports_vision'],
    key_preview=cred['byok_key_preview'])]}, bpy.context.window_manager)
P.apply_local(saved[2])
bpy.context.preferences.view.show_tooltips = saved[3]
del P._qa_chip_label
P._redraw()
result = True
"""
BYOK_ON = """
import bpy
from mixar.modules.byok.core import preference_state as P, credential_state as C
wm = bpy.context.window_manager
# The preference mirror says "key active" (the server's word) ...
P.apply_local({'mixar_agent_model_byok_active': True})
# ... and the credential fetch lands afterwards: the chip must follow it
# (picker_mirror runs from the credential apply), not wait for the next pick.
C.apply_from_payload({'byok_active': True, 'items': [dict(
    provider='qa-key-provider', model='qa-key-model', supports_vision=True,
    key_preview='sk-...qa')]}, wm)
assert wm.byok_current_provider == 'qa-key-provider'
P._redraw()
result = wm.mixar_agent_source
"""


def close_menus(qa):
    mp.close_popup(qa)


def redraw_window_of(qa, target):
    qa.eval(f"widget=drv.find_one(**{target!r})\n"
            "win=widget['_win']\n"
            "with bpy.context.temp_override(window=win, area=next(iter(win.screen.areas))):\n"
            "    bpy.ops.wm.redraw_timer(type='DRAW_WIN_SWAP', iterations=1)\n"
            "result=True")
    time.sleep(.25)


def capture(qa, name, target, margin=1500):
    """Targeted framebuffer snap of the widget's own window."""
    redraw_window_of(qa, target)
    path = str(OUT / (name + '.png'))
    qa.cmd('snap', path=path, target=target, margin=margin)
    return path


def capture_island(qa, name):
    """The island's glass window can snap black; QA_REGION_CAPTURE=1 reads
    its region framebuffers instead (same path as island_rules_e2e)."""
    redraw_window_of(qa, PICKER)
    path = OUT / (name + '.png')
    if os.environ.get('QA_REGION_CAPTURE') == '1':
        window = qa.find(**PICKER)['widgets'][0]['window']
        qa.eval(f"import qa_region_capture\nqa_region_capture.start({str(path)!r}, {window})\nresult=True")
        qa.wait('__import__("qa_region_capture").done', timeout=10)
        qa.eval('import qa_region_capture\nassert qa_region_capture.error is None, qa_region_capture.error\nresult=True')
    else:
        qa.cmd('snap', path=str(path), target=PICKER, margin=400)
    return str(path)


def run(qa):
    qa.step('dismiss_splash', qa.dismiss_splash)
    qa.step('open_island', qa.eval, 'result=str(bpy.ops.mixar.agent_bubble_show_window())')
    qa.step('install_fixture', qa.eval, SETUP)
    snaps = []
    try:
        # 1. Hosted pick with a thinking level -> Mixie, "<model> · <Level>".
        qa.step('chip_reads_model_and_level', qa.wait,
                f"bpy.context.window_manager.mixar_agent_chip_name == {CHIP_WITH_LEVEL!r} and "
                "bpy.context.window_manager.mixar_agent_source == 'MIXIE'", timeout=5)
        assert mp.chip(qa) == ('MIXIE', 'Mixie', CHIP_WITH_LEVEL, 'OK'), mp.chip(qa)
        qa.step('dict_stays_model_only', qa.eval,
                "from mixar.modules.byok.core import preference_state as P\n"
                "assert P.snapshot()['mixar_agent_model_label'] == 'QA Model'\n"
                "assert not bpy.context.window_manager.mixar_agent_model_byok_active\n"
                "result=True")
        assert qa.find(**PICKER)['widgets'], 'the island model chip is not on screen'
        snaps.append(qa.step('chip_level_capture', capture_island, qa, 'chip_level'))
        qa.step('open_hosted', mp.open_popup, qa)
        assert mp.open_tab(qa) == 'MIXIE', mp.open_tab(qa)
        assert mp.rows(qa) == [('Mixar default', True), ('QA Model', True)], mp.rows(qa)
        qa.wait(f"bool(drv.find(**{mp.THINKING!r}, text='Thinking: High', contains=True))", timeout=5)
        snaps.append(qa.step('hosted_popup_capture', capture, qa, 'hosted_popup', mp.THINKING))
        # The disclosure is an RNA toggle; the popup re-lays with the levels.
        qa.step('open_levels', qa.click, **mp.THINKING)
        qa.wait(f"sorted(w['text'] for w in drv.find(**{mp.PICK!r})) == "
                "['High', 'Low', 'Mixar default', 'QA Model']", timeout=5)
        snaps.append(qa.step('levels_capture', capture, qa, 'hosted_levels', mp.THINKING))
        close_menus(qa)

        # 2. A user key moves the chip to the key, re-mirrored by the
        #    credential state landing after the preference mirror.
        source = qa.step('byok_on', qa.eval, BYOK_ON)
        assert source == 'KEY', source
        # The fixture's key is never on this computer: once the off-thread
        # presence check lands, the chip says so (red, "key needed").
        qa.step('chip_reads_key', qa.wait,
                "bpy.context.window_manager.mixar_agent_source == 'KEY' and "
                "bpy.context.window_manager.mixar_agent_source_state == 'KEY_NEEDED'", timeout=10)
        assert mp.chip(qa) == ('KEY', 'QA Key Provider', 'QA Key Model', 'KEY_NEEDED'), mp.chip(qa)
        snaps.append(qa.step('chip_key_capture', capture_island, qa, 'chip_key'))

        # 3. The card opens on the key tab: the key's model (one the catalog
        #    does not list still gets its row), greyed until the key is
        #    entered here, the note saying why, and "Enter key…".
        qa.step('open_key_tab', mp.open_popup, qa)
        assert mp.open_tab(qa) == 'KEY', mp.open_tab(qa)
        assert mp.rows(qa) == [('QA Key Model', False)], mp.rows(qa)
        assert qa.find(surface='model_card_note', text='Key needed on this computer')['widgets']
        enter = qa.find(**mp.SETTINGS_ROW)['widgets']
        assert len(enter) == 1 and enter[0]['enabled'] and enter[0]['text'] == 'Enter key…', enter
        snaps.append(qa.step('key_popup_capture', capture, qa, 'key_popup', mp.SETTINGS_ROW))
        close_menus(qa)
        return {'snaps': snaps, 'real_backend_mutations': 0}
    finally:
        close_menus(qa)
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_chip_label_e2e', run)
