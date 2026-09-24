#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""No paid calls: Enter activates the legacy viewport popup's chat field.

This uses the same Scene property as the island, in a native VIEW_3D popup.
Both Enter keys must begin editing, with native commit/cancel and no send.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import ScenarioFail, run_scenario

ROOT = Path(__file__).resolve().parents[2]
FIELD = {'popup': True, 'prop': 'mixie_chat_input'}
SCENE = 'drv.main_window().scene'


def require(value, message):
    if not value:
        raise ScenarioFail(message)


def field(qa):
    return qa.find(**FIELD)['widgets'][0]


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/chat-popup-enter-qa')) / 'snaps'
    out.mkdir(parents=True, exist_ok=True)
    original = qa.eval(f'result={SCENE}.mixie_chat_input')
    window = qa.eval('result=drv.main_window().as_pointer()')
    qa.eval(f'''
import os, sys
assert os.environ.get('MIXAR_QA') == '1'
sys.path.insert(0, {str(ROOT / 'tests/qa')!r})
import chat_send_probe
chat_send_probe.install()
bpy.ops.mixar.bubble_minimise()
result=True
''')
    try:
        for key in ('RET', 'NUMPAD_ENTER'):
            draft = f'Popup draft {key}'
            qa.eval(f'''
w=drv.main_window()
w.scene.mixie_chat_input={draft!r}
a=next(a for a in w.screen.areas if a.type=='VIEW_3D')
r=next(r for r in a.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mixie_chat.agent_bubble_show('INVOKE_DEFAULT')
result=True
''')
            qa.wait(f'bool(drv.find(**{FIELD!r}))', timeout=5)
            qa.eval(f"w=drv.find_one(**{FIELD!r}); drv.move_to(w['_win'], *w['center']); result=True")
            require(not field(qa).get('text_edit'), 'Popup was already editing before Enter')
            qa.press(key, window=window)
            qa.cmd('snap', path=str(out / f'{key.lower()}-activated.png'), target=FIELD, margin=160)
            qa.step(f'popup_{key}_activates_editing', require,
                    bool(field(qa).get('text_edit')), 'First Enter did not keep the popup field editing')
            qa.press('END', window=window)
            qa.cmd('type', text=' edited', window=window)
            qa.press(key, window=window)
            expected = draft + ' edited'
            qa.step(f'popup_{key}_commits_without_sending', require,
                    qa.eval(f'result={SCENE}.mixie_chat_input') == expected,
                    'Native Enter did not commit the edit')
            require(not field(qa).get('text_edit'), 'Commit left the field editing')
            qa.press(key, window=window)
            qa.press('END', window=window)
            qa.cmd('type', text=' discard', window=window)
            qa.press('ESC', window=window)
            qa.step(f'popup_{key}_escape_cancels', require,
                    qa.eval(f'result={SCENE}.mixie_chat_input') == expected,
                    'Escape did not restore the committed draft')
            require(qa.eval("result=len(__import__('chat_send_probe').calls)") == 0,
                    'Popup Enter sent a message')
            qa.press('ESC', window=window)
            qa.wait(f'not drv.find(**{FIELD!r})', timeout=3)
        return {'enter_activates': True, 'numpad_enter_activates': True,
                'native_commit_cancel': True, 'backend_calls': 0, 'snapshots': str(out)}
    finally:
        # One Escape cancels an active edit; a second closes the popup.
        for _ in range(2):
            if qa.find(**FIELD)['total']:
                qa.press('ESC', window=window)
        qa.eval(f'{SCENE}.mixie_chat_input={original!r}; '
                "__import__('chat_send_probe').uninstall(); result=True")


if __name__ == '__main__':
    run_scenario('chat_popup_enter_activation_e2e', run)
