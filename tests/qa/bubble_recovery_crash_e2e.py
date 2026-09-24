#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay the native Recover Last Session path in an isolated offline QA app.

Set QA_RECOVERY_FILE to a legacy .mixar fixture (runtime bubble regions saved
without TEMP_REGIONDATA), QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT.
Stage with QA_RECOVERY_STAGE=1, force-stop only that QA process, relaunch the
isolated harness, then run without QA_RECOVERY_STAGE. The dedicated quit.blend
survives that stop. Never reads or overwrites the user's quit.blend.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from bubble_checkpoint_crash_e2e import capture
from mixie_open_type_send_e2e import SCENE, draft_is, open_pill, type_draft


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/bubble-recovery-crash'))
    out.mkdir(parents=True, exist_ok=True)
    root = out / 'recovery'
    root.mkdir(exist_ok=True)
    qa.eval("import os; assert os.environ.get('MIXAR_QA') == '1'; result=True")
    if os.environ.get('QA_RECOVERY_STAGE') == '1':
        fixture = str(Path(os.environ['QA_RECOVERY_FILE']).resolve())
        qa.eval('import shutil; '
                f'shutil.copyfile({fixture!r}, {str(root / "quit.blend")!r}); result=True')
        return {'staged': str(root / 'quit.blend'), 'next': 'Force-stop only this QA app, relaunch, replay'}
    assert (root / 'quit.blend').is_file(), 'Stage a recovery fixture first'
    old_temp = qa.eval('result=bpy.context.preferences.filepaths.temporary_directory')
    try:
        qa.eval(f'bpy.context.preferences.filepaths.temporary_directory={str(root)!r}; result=True')
        # The second read frees the first read's dormant bubble screens: the
        # old binary crashed in agent_ui_motion_region_free here.
        for index in range(3):
            qa.step(f'recover_last_session_{index}', qa.eval,
                    'with bpy.context.temp_override(window=drv.main_window()):\n'
                    '    result=str(bpy.ops.wm.recover_last_session())')
            qa.wait("bool(drv.find(surface='pill_cat'))", timeout=12)
            assert qa.eval(f'result={SCENE}.get("qa_checkpoint_marker")') == 'before'
        qa.eval('from mixar.modules.space_mixie_chat.core.session import get_session_manager; '
                f'get_session_manager().set_connected({SCENE}); '
                'bpy.context.window_manager.mixie_chat_is_logged_in=True; result=True')
        open_pill(qa)
        before = qa.eval(f'result={SCENE}.mixie_chat_input')
        type_draft(qa, ' Recovered safely')
        draft_is(qa, before + ' Recovered safely')
        capture(qa, out, 'legacy-recovery-editable')
        # Bypass the Python purge only in this isolated fixture so the native
        # writer must handle live motion state, as autosave/recovery can do.
        fresh = str(out / 'runtime-regions-fixed.mixar')
        qa.eval(f'''
handlers = bpy.app.handlers.save_pre
removed = [h for h in handlers if h.__name__ == 'on_save_pre' and 'agent_bubble' in h.__module__]
for h in removed:
    handlers.remove(h)
try:
    result = str(bpy.ops.wm.save_as_mainfile(filepath={fresh!r}, copy=True, compress=True))
finally:
    handlers.extend(removed)
''')
        for index in range(2):
            qa.step(f'new_runtime_file_read_{index}', qa.eval,
                    'with bpy.context.temp_override(window=drv.main_window()):\n'
                    f'    result=str(bpy.ops.wm.open_mainfile(filepath={fresh!r}))')
            qa.wait("bool(drv.find(surface='pill_cat'))", timeout=12)
        return {'recover_last_session_reads': 3, 'legacy_fixture': True,
                'typing_after_recovery': True, 'new_runtime_file_reads': 2,
                'evidence': str(out)}
    finally:
        qa.eval(f'bpy.context.preferences.filepaths.temporary_directory={old_temp!r}; result=True')


if __name__ == '__main__':
    run_scenario('bubble_recovery_crash_e2e', run)
