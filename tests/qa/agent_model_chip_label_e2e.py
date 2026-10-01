#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Island Model chip label + the BYOK note; no credits, credentials or writes.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4811 \
  QA_SCENARIO_OUT=/tmp/chip-label python3 tests/qa/agent_model_chip_label_e2e.py
Run in an isolated QA app. Inspect the saved PNGs as well as the state verdict.

Proves, against the real C++ chip and the real native menu:
  1. a hosted pick WITH a thinking level draws `<model> · <Level>` on the chip;
  2. a user key flips the chip to `model_menu.BYOK_CHIP_TEXT`, even when the
     credential state lands AFTER the preference mirror (the re-mirror path);
  3. the open menu's NOTE row names the key's provider and model.
Only the preference service and the credential mirror are synthetic (memory
only — `credential_state` never touches the keychain, and the fixture restores
the account's real mirror on exit). No PUT/DELETE reaches the backend.
"""
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chip-label'))
OUT.mkdir(parents=True, exist_ok=True)
PICKER = {'but_type': 'Pulldown', 'area_type': 'AGENT_BUBBLE'}
MODEL = {'op': 'MIXAR_OT_agent_model_set', 'popup': True}
KEY_ROW = {'op': 'MIXAR_BYOK_OT_open_dialog', 'popup': True}
CHIP_WITH_LEVEL = 'QA Model · High'
NOTE_TEXT = 'Your key: QA Key Provider · QA Key Model'
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
assert wm.mixar_agent_model_label == 'Custom', wm.mixar_agent_model_label
# ... and the credential fetch lands afterwards, on a chip someone smudged:
# the credential mirror must recompose it, not leave it to the next pick.
wm.mixar_agent_model_label = 'stale'
C.apply_from_payload({'byok_active': True, 'items': [dict(
    provider='qa-key-provider', model='qa-key-model', supports_vision=True,
    key_preview='sk-...qa')]}, wm)
assert wm.byok_current_provider == 'qa-key-provider'
P._redraw()
result = wm.mixar_agent_model_label
"""


def close_menus(qa):
    for _ in range(2):
        widgets = qa.find(popup=True)['widgets']
        if not widgets:
            return
        for window in {widget['window'] for widget in widgets}:
            qa.press('ESC', window=window)
        time.sleep(.2)
    qa.wait('not bool(drv.find(popup=True))', timeout=5)


def open_picker(qa):
    qa.click(**PICKER)
    # The first native click after opening a fresh island can commit its
    # composer focus. Retry once only when the popup demonstrably stayed shut.
    if not qa.find(**KEY_ROW)['widgets']:
        qa.click(**PICKER)
    qa.wait("bool(drv.find(op='MIXAR_BYOK_OT_open_dialog', popup=True))", timeout=5)


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
        # 1. Hosted pick with a thinking level -> "<model> · <Level>".
        qa.step('chip_reads_model_and_level', qa.wait,
                f"bpy.context.window_manager.mixar_agent_model_label == {CHIP_WITH_LEVEL!r}",
                timeout=5)
        qa.step('dict_stays_model_only', qa.eval,
                "from mixar.modules.byok.core import preference_state as P\n"
                "assert P.snapshot()['mixar_agent_model_label'] == 'QA Model'\n"
                "assert not bpy.context.window_manager.mixar_agent_model_byok_active\n"
                "result=True")
        assert qa.find(**PICKER)['widgets'], 'the island Model chip is not on screen'
        snaps.append(qa.step('chip_level_capture', capture_island, qa, 'chip_level'))
        qa.step('open_hosted', open_picker, qa)
        rows = qa.find(**MODEL)['widgets']
        assert [r['text'] for r in rows] == ['QA Model'] and rows[0]['enabled'], rows
        assert not qa.find(text='Your key', contains=True, popup=True)['widgets']
        qa.wait("bool(drv.find(text='Thinking: High', popup=True))", timeout=5)
        snaps.append(qa.step('hosted_menu_capture', capture, qa, 'hosted_menu', KEY_ROW))
        close_menus(qa)

        # 2. A user key overrides the pick -> the BYOK indicator, re-mirrored
        #    by the credential state landing after the preference mirror.
        label = qa.step('byok_on', qa.eval, BYOK_ON)
        assert label == 'Custom', label
        qa.step('chip_reads_byok', qa.wait,
                "bpy.context.window_manager.mixar_agent_model_label == 'Custom' and "
                "bpy.context.window_manager.mixar_agent_model_byok_active",
                timeout=5)
        snaps.append(qa.step('chip_byok_capture', capture_island, qa, 'chip_byok'))

        # 3. The open menu names the key's provider and model.
        qa.step('open_byok', open_picker, qa)
        note = qa.find(text=NOTE_TEXT, popup=True)['widgets']
        assert len(note) == 1 and not note[0]['enabled'], note
        assert all(not r['enabled'] for r in qa.find(**MODEL)['widgets'])
        assert qa.find(**KEY_ROW)['widgets'][0]['enabled']
        assert 'remove' in qa.find(**KEY_ROW)['widgets'][0]['text'].lower()
        snaps.append(qa.step('byok_menu_capture', capture, qa, 'byok_menu', KEY_ROW))
        close_menus(qa)
        return {'snaps': snaps, 'real_backend_mutations': 0}
    finally:
        close_menus(qa)
        qa.step('restore_fixture', qa.eval, CLEANUP)


if __name__ == '__main__':
    run_scenario('agent_model_chip_label_e2e', run)
