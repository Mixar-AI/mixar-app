#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native island Rules click/edit/close/reopen replay.

Run against an isolated QA profile with QA_HARNESS and MIXAR_QA_PORT set.
Global storage is redirected to a temporary file for the whole scenario.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def snap(qa, path, button):
    if os.environ.get('QA_REGION_CAPTURE') == '1':
        window = qa.find(**button)['widgets'][0]['window']
        qa.eval(f"import qa_region_capture\nqa_region_capture.start({str(path)!r}, {window})\nresult=True")
        qa.wait('__import__("qa_region_capture").done', timeout=10)
        qa.eval('import qa_region_capture\nassert qa_region_capture.error is None, qa_region_capture.error\nresult=True')
    else:
        qa.cmd('snap', path=str(path), target=button, margin=1400)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/island-rules-evidence'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("hasattr(bpy.types.WindowManager, 'mixie_chat_rules_visible')", timeout=30)
    qa.eval("""
import os, tempfile
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import rules_global
assert os.environ.get('MIXAR_QA') == '1'
f = drv._island_rules_test = SimpleNamespace(
    scratch=tempfile.TemporaryDirectory(prefix='island-rules-'),
    original_path=rules_global._store_path, scene=drv.main_window().scene)
assert not len(f.scene.mixie_chat_messages), 'Use a fresh QA conversation'
f.rules = f.scene.mixie_chat_rules
f.draft = f.scene.mixie_chat_input
rules_global._store_path = lambda: f.scratch.name + '/global.json'
f.scene.mixie_chat_rules = ''
f.scene.mixie_chat_input = 'Keep this draft'
result = True
""")
    try:
        qa.step('open_island', qa.open_chat)
        button = dict(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_add_rules')
        qa.wait("bool(drv.find(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_add_rules'))", timeout=10)
        snap(qa, out / 'button.png', button)
        qa.step('open_rules', qa.click, **button)
        qa.wait('bpy.context.window_manager.mixie_chat_rules_visible', timeout=10)
        qa.wait("bool(drv.find(surface='chat_rules_editor'))", timeout=10)
        editor = qa.step('focus_editor', qa.click, surface='chat_rules_editor')
        window = editor['window']
        qa.cmd('type', text='Use metric units', window=window)
        qa.step('submit_rule', qa.click, surface='chat_rules_submit')
        qa.wait("any(r.text == 'Use metric units' for r in "
                "bpy.context.window_manager.mixie_chat_rule_entries)", timeout=10)
        snap(qa, out / 'editor.png', button)
        qa.step('close_editor', qa.click, surface='chat_rules_close')
        qa.wait('not bpy.context.window_manager.mixie_chat_rules_visible', timeout=5)
        qa.eval("assert drv._island_rules_test.scene.mixie_chat_input == 'Keep this draft'\nresult=True")
        qa.step('reopen_editor', qa.click, **button)
        qa.wait("bool(drv.find(surface='chat_rules_editor'))", timeout=5)
        qa.eval("assert len(bpy.context.window_manager.mixie_chat_rule_entries) == 1\nresult=True")
        qa.click(surface='chat_rules_editor')  # Keyboard events belong to the hovered region.
        qa.press('ESC', window=window)
        qa.wait('not bpy.context.window_manager.mixie_chat_rules_visible', timeout=5)
        qa.step('restore_composer_focus', qa.click,
                area_type='AGENT_BUBBLE', prop='mixie_chat_input')
        qa.cmd('type', text=' editable', window=window)
        qa.click(**button)  # Commit the native field before reading its RNA value.
        qa.wait("'editable' in drv._island_rules_test.scene.mixie_chat_input", timeout=5)
        qa.click(surface='chat_rules_close')
        qa.eval("""
f = drv._island_rules_test
m = f.scene.mixie_chat_messages.add()
m.sender = 'AGENT'
m.content = 'Local QA transcript fixture'
for w in bpy.context.window_manager.windows:
    for a in w.screen.areas:
        a.tag_redraw()
result = True
""")
        qa.step('open_with_transcript', qa.click, **button)
        qa.wait("bool(drv.find(surface='chat_rules_editor'))", timeout=5)
        snap(qa, out / 'with-transcript.png', button)
        qa.step('close_with_transcript', qa.click, surface='chat_rules_close')
        qa.wait('not bpy.context.window_manager.mixie_chat_rules_visible', timeout=5)
        return {'passed': True, 'paid_requests': 0, 'draft_preserved': True}
    finally:
        qa.eval("""
from mixar.modules.space_mixie_chat.core import rules_global, rules_api
f = drv._island_rules_test
bpy.context.window_manager.mixie_chat_rules_visible = False
rules_global._store_path = f.original_path
f.scene.mixie_chat_rules = f.rules
f.scene.mixie_chat_input = f.draft
f.scene.mixie_chat_messages.clear()
rules_api.refresh_rules_ui()
f.scratch.cleanup()
del drv._island_rules_test
result = True
""")


if __name__ == '__main__':
    run_scenario('island_rules_e2e', run)
