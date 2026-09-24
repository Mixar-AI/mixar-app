#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native Checkpoints and Project Rules UI replay.

Launch an isolated offline Dev app with the QA harness. Set QA_HARNESS,
MIXAR_QA_PORT and QA_SCENARIO_OUT; screenshots and results remain local.
Real controls/stores are exercised with a temporary global-rules/checkpoint
root. The checkpoint check opens the card; it never restores a project.
"""
from collections import Counter
import os
from pathlib import Path
import sys
import time

from PIL import Image

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from mixie_open_type_send_e2e import open_pill, warp

CHECKPOINTS = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_show_checkpoints'}
RULES = {'area_type': 'AGENT_BUBBLE', 'op': 'MIXIE_CHAT_OT_add_rules'}
EDITOR = {'surface': 'chat_rules_editor'}
SUBMIT = {'surface': 'chat_rules_submit'}
PROJECT = {'surface': 'chat_rules_scope', 'index': 0, 'text': 'This project'}
GLOBAL = {'surface': 'chat_rules_scope', 'index': 0, 'text': 'All projects'}
SCENE = 'drv.main_window().scene'
SETUP = r'''
import os, tempfile
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import rules_api, rules_global, checkpoint_store
from mixar.modules.space_mixie_chat.core.session import get_session_manager
assert os.environ.get('MIXAR_QA') == '1'
f = drv._checkpoint_rules_qa = SimpleNamespace(
    scratch=tempfile.TemporaryDirectory(prefix='checkpoint-rules-'),
    global_path=rules_global._store_path, checkpoint_root=checkpoint_store.checkpoints_root,
    scene=drv.main_window().scene)
f.old_rules = f.scene.mixie_chat_rules
f.old_session = f.scene.mixie_session_id
rules_global._store_path = lambda: str(Path(f.scratch.name) / 'global.json')
checkpoint_store.checkpoints_root = lambda: str(Path(f.scratch.name) / 'checkpoints')
f.scene.mixie_chat_rules = ''
f.scene.mixie_session_id = 'qa-checkpoint-rules-ui'
f.scene.mixie_chat_messages.clear()
f.scene.mixie_chat_input = ''
get_session_manager().set_connected(f.scene)
wm = bpy.context.window_manager
wm.mixie_chat_is_logged_in = True
wm.mixar_bubble_tab = 'AGENT'
wm.mixie_chat_history_visible = False
wm.mixie_chat_rules_visible = False
rules_api.refresh_rules_ui()
result = True
'''
CLEANUP = r'''
from mixar.modules.space_mixie_chat.core import rules_api, rules_global, checkpoint_store
from mixar.modules.space_mixie_chat.core.session import get_session_manager
f = drv._checkpoint_rules_qa
rules_global._store_path = f.global_path
checkpoint_store.checkpoints_root = f.checkpoint_root
f.scene.mixie_chat_rules = f.old_rules
f.scene.mixie_session_id = f.old_session
get_session_manager().set_connected(f.scene)
bpy.context.window_manager.mixie_chat_rules_visible = False
bpy.context.window_manager.mixie_chat_history_visible = False
rules_api.refresh_rules_ui()
f.scratch.cleanup()
del drv._checkpoint_rules_qa
result = True
'''


def click(qa, target):
    warp(qa, target)
    qa.click(**target)
    time.sleep(.18)


def press(qa, key, **mods):
    window = qa.find(**EDITOR)['widgets'][0]['window']
    qa.press(key, window=window, **mods)


def replace(qa, text):
    click(qa, EDITOR)
    apple = qa.eval("import sys; result=sys.platform == 'darwin'")
    press(qa, 'A', oskey=apple, ctrl=not apple)
    qa.cmd('type', window=qa.find(**EDITOR)['widgets'][0]['window'], text=text)


def rows(qa):
    return qa.eval('from mixar.modules.space_mixie_chat.core import rules_api; '
                   f'result=rules_api.list_unified({SCENE})')


def capture(qa, out, name, target=EDITOR):
    time.sleep(.35)
    path = out / f'{name}.png'
    qa.eval(f'w=drv.find_one(**{target!r})["_win"]\n'
            'with bpy.context.temp_override(window=w):\n'
            f'    result=w.mixar_qa_capture_frame(filepath={str(path)!r})')


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/checkpoint-rules-ui'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.WindowManager,'mixie_chat_rule_entries')", timeout=30)
    qa.eval(f'import sys; sys.path.insert(0, {str(Path(__file__).parent)!r}); result=True')
    qa.step('isolated_rule_stores', qa.eval, SETUP)
    try:
        open_pill(qa)
        cp = qa.find(**CHECKPOINTS)['widgets'][0]['rect']
        rules = qa.find(**RULES)['widgets'][0]['rect']
        assert cp[2] < rules[0], (cp, rules)
        assert abs((cp[2] - cp[0]) - (cp[3] - cp[1])) <= 2, cp
        assert qa.find(**CHECKPOINTS)['widgets'][0]['text'] == ''
        capture(qa, out, 'header', CHECKPOINTS)
        # All four header discs use the same opaque accent fill. Compare
        # their dominant green framebuffer samples, excluding glyph pixels.
        colors = []
        with Image.open(out / 'header.png') as image:
            for op in ('show_history', 'new_session', 'show_checkpoints', 'add_rules'):
                rect = qa.find(area_type='AGENT_BUBBLE',
                               op='MIXIE_CHAT_OT_' + op)['widgets'][0]['rect']
                x0, y0, x1, y1 = map(round, rect)
                pixels = image.convert('RGB').crop((x0, image.height-y1, x1, image.height-y0))
                greens = [c for c in pixels.getdata() if c[1] > c[0]*1.3 and c[1] > c[2]*1.2]
                assert greens, (op, rect)
                colors.append(Counter(greens).most_common(1)[0][0])
        assert all(max(abs(a-b) for a, b in zip(colors[0], c)) <= 2 for c in colors), colors
        # The checkpoint glyph has a clear inset on every side of its disc.
        with Image.open(out / 'header.png') as image:
            x0, y0, x1, y1 = map(round, cp)
            tile = image.convert('RGB').crop((x0, image.height-y1, x1, image.height-y0))
            glyph = [(x, y) for y in range(tile.height) for x in range(tile.width)
                     if min(tile.getpixel((x, y))) > 155]
            assert glyph
            inset = min(min(x for x, y in glyph), min(y for x, y in glyph),
                        tile.width - 1 - max(x for x, y in glyph),
                        tile.height - 1 - max(y for x, y in glyph))
            assert inset >= tile.width * .09, (inset, tile.size)
        qa.step('icon_only_header_with_matching_colors_and_padding', lambda: colors)
        click(qa, CHECKPOINTS)
        qa.wait("bool(drv.find(surface='chat_checkpoints_close'))", timeout=5)
        assert qa.eval(f'result=len({SCENE}.mixie_chat_messages)') == 0
        capture(qa, out, 'checkpoints-empty', {'surface': 'chat_checkpoints_close'})
        qa.step('checkpoints_visible_before_first_message', lambda: True)
        click(qa, {'surface': 'chat_checkpoints_close'})
        click(qa, RULES)
        qa.wait("bool(drv.find(surface='chat_rules_editor'))", timeout=5)
        assert not qa.find(**SUBMIT)['widgets'][0]['enabled']
        capture(qa, out, 'rules-empty')
        qa.step('rules_visible_before_first_message', lambda: True)
        replace(qa, '   ')
        press(qa, 'RET')
        assert rows(qa) == []
        assert not qa.find(**SUBMIT)['widgets'][0]['enabled']
        qa.step('blank_rule_stays_unsaved', lambda: True)
        replace(qa, 'Use meters for all dimensions.')
        press(qa, 'RET', shift=True)
        qa.cmd('type', window=qa.find(**EDITOR)['widgets'][0]['window'],
               text='Keep materials reusable across objects.')
        click(qa, SUBMIT)
        saved = rows(qa)
        assert len(saved) == 1 and '\n' in saved[0]['text'], saved
        rule_id = saved[0]['id']
        capture(qa, out, 'rules-saved')
        qa.step('multiline_rule_saved_from_native_button', lambda: saved[0]['text'])
        click(qa, {'surface': 'chat_rules_toggle', 'index': 0})
        assert rows(qa)[0]['enabled'] is False
        capture(qa, out, 'rules-disabled')
        click(qa, {'surface': 'chat_rules_toggle', 'index': 0})
        assert rows(qa)[0]['enabled'] is True
        qa.step('rule_toggle_roundtrip', lambda: True)
        click(qa, {'surface': 'chat_rules_edit', 'index': 0})
        assert qa.find(**SUBMIT)['widgets'][0]['text'] == 'Save'
        replace(qa, 'Keep dimensions in centimeters.')
        press(qa, 'RET')
        assert rows(qa)[0]['text'] == 'Keep dimensions in centimeters.'
        assert rows(qa)[0]['id'] == rule_id
        qa.step('edit_preserves_rule_identity', lambda: True)
        assert qa.find(**PROJECT)['widgets'][0]['sel']
        assert not qa.find(**GLOBAL)['widgets'][0].get('sel', False)
        click(qa, {'surface': 'chat_rules_edit', 'index': 0})
        replace(qa, 'An unsaved edit that must survive selecting the active scope.')
        click(qa, PROJECT)
        assert rows(qa)[0]['scope'] == 'project'
        assert rows(qa)[0]['id'] == rule_id
        assert qa.find(**SUBMIT)['widgets'][0]['text'] == 'Save'
        press(qa, 'RET')
        assert 'unsaved edit' in rows(qa)[0]['text']
        click(qa, {'surface': 'chat_rules_edit', 'index': 0})
        replace(qa, 'Keep dimensions in centimeters.')
        press(qa, 'RET')
        click(qa, GLOBAL)
        assert rows(qa)[0]['scope'] == 'global'
        assert qa.find(**GLOBAL)['widgets'][0]['sel']
        assert not qa.find(**PROJECT)['widgets'][0].get('sel', False)
        capture(qa, out, 'rules-global')
        global_rule = rows(qa)[0]
        click(qa, GLOBAL)
        assert rows(qa)[0] == global_rule
        click(qa, PROJECT)
        assert rows(qa)[0]['scope'] == 'project'
        assert qa.find(**PROJECT)['widgets'][0]['sel']
        qa.step('explicit_scope_roundtrip_and_active_choice_preserves_edit', lambda: True)
        if qa.eval("import sys; result=sys.platform == 'darwin'"):
            frame = qa.eval("import zen_ui_native as native; result=native.frame('bubble')")
            try:
                qa.eval("import zen_ui_native as native; result=native.frame('bubble', size=(480, 340))")
                time.sleep(.5)
                project = qa.find(**PROJECT)['widgets'][0]['rect']
                global_choice = qa.find(**GLOBAL)['widgets'][0]['rect']
                assert project[2] <= global_choice[0], (project, global_choice)
                click(qa, GLOBAL)
                assert rows(qa)[0]['scope'] == 'global'
                click(qa, PROJECT)
                assert rows(qa)[0]['scope'] == 'project'
                capture(qa, out, 'rules-small-scope')
                qa.step('small_window_scope_choices_remain_reachable', lambda: True)
            finally:
                qa.eval(f"import zen_ui_native as native; result=native.frame('bubble', size={tuple(frame[2:])!r})")
                time.sleep(.5)
        # Long subsequent drafts must scroll internally, keeping Save reachable.
        click(qa, {'surface': 'chat_rules_edit', 'index': 0})
        replace(qa, 'Wrap this reference name: ' + 'reference_' * 35)
        for i in range(9):
            press(qa, 'RET', shift=True)
            qa.cmd('type', window=qa.find(**EDITOR)['widgets'][0]['window'],
                   text=f'Rule line {i}: preserve the scene and explain the changes.')
        editor = qa.find(**EDITOR)['widgets'][0]['rect']
        button = qa.find(**SUBMIT)['widgets'][0]['rect']
        assert 0 <= button[1] < button[3] <= editor[1], (editor, button)
        capture(qa, out, 'rules-long-draft')
        # Constrain the real companion window, then restore its native frame.
        if qa.eval("import sys; result=sys.platform == 'darwin'"):
            frame = qa.eval("import zen_ui_native as native; result=native.frame('bubble')")
            try:
                qa.eval("import zen_ui_native as native; result=native.frame('bubble', size=(480, 340))")
                time.sleep(.5)
                warp(qa, EDITOR)
                button = qa.find(**SUBMIT)['widgets'][0]['rect']
                editor = qa.find(**EDITOR)['widgets'][0]['rect']
                assert 0 <= button[1] < button[3] <= editor[1], (editor, button)
                capture(qa, out, 'rules-small-window')
                qa.step('small_window_keeps_actions_reachable', lambda: True)
            finally:
                qa.eval(f"import zen_ui_native as native; result=native.frame('bubble', size={tuple(frame[2:])!r})")
                time.sleep(.5)
        press(qa, 'ESC')  # cancel editing; keep the existing saved rule
        assert rows(qa)[0]['text'] == 'Keep dimensions in centimeters.'
        qa.step('long_draft_keeps_actions_visible_and_cancel_preserves_rule', lambda: True)
        click(qa, {'surface': 'chat_rules_delete', 'index': 0})
        assert len(rows(qa)) == 1
        assert qa.find(surface='chat_rules_delete', index=0)['widgets'][0]['sel']
        click(qa, {'surface': 'chat_rules_delete', 'index': 0})
        assert rows(qa) == []
        qa.step('delete_requires_confirmation', lambda: True)
        qa.eval('from mixar.modules.space_mixie_chat.core import rules_api\n'
                f'for i in range(12):\n    rules_api.add_rule({SCENE}, f"Layout fixture rule {{i}}: keep names descriptive.")\n'
                'rules_api.refresh_rules_ui()\nresult=True')
        time.sleep(.3)
        before = qa.find(surface='chat_rules_delete')['widgets']
        warp(qa, {'surface': 'chat_rules_list'})
        for _ in range(8):
            press(qa, 'WHEELDOWNMOUSE')
        time.sleep(.5)
        after = qa.find(surface='chat_rules_delete')['widgets']
        assert max(w['index'] for w in after) > max(w['index'] for w in before), (before, after)
        capture(qa, out, 'rules-scrolled')
        qa.step('long_rule_list_scrolls', lambda: True)
        click(qa, {'surface': 'chat_rules_close'})
        qa.wait('not bpy.context.window_manager.mixie_chat_rules_visible', timeout=4)
        qa.step('close_restores_chat', lambda: True)
        return {'paid_requests': 0, 'screenshots': str(out)}
    finally:
        qa.eval(CLEANUP)


if __name__ == '__main__':
    run_scenario('checkpoint_rules_ui_e2e', run)
