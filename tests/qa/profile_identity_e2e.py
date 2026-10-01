#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Offline account/file isolation; no credits or real account credentials.

Run only in a disposable QA instance with auth refresh disabled and an
in-memory keyring. Creates synthetic legacy files and changes the open file.
QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4798 \
    python3 tests/qa/profile_identity_e2e.py
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    qa.press('ESC')
    qa.step('legacy_fixture', qa.eval, """
import os
from mixar.modules.space_mixie_chat.core import account_identity as identity
from mixar.modules.space_mixie_chat.ui.operators import auth_ops
assert os.environ.get('MIXAR_QA') == '1'
assert type(__import__('keyring').get_keyring()).__name__ == 'QAMemoryKeyring'
auth_ops._auth_check_background_safe = lambda: None
identity.unregister()
bpy.types.Scene.mixie_chat_user_id = bpy.props.StringProperty(options={'SKIP_SAVE'})
second = bpy.data.scenes.new('QA Other Scene')
for scene in bpy.data.scenes:
    scene.mixie_chat_user_id = 'author@example.invalid'
legacy = os.path.join(os.environ['MIXAR_QA_OUT'], 'identity-legacy.blend')
bpy.ops.wm.save_as_mainfile(filepath=legacy)
identity.register()
bpy.context.scene.mixie_chat_user_id = 'reader@example.invalid'
result = True
""")
    qa.step('immediate_file_load', qa.eval, """
import os
legacy = os.path.join(os.environ['MIXAR_QA_OUT'], 'identity-legacy.blend')
bpy.ops.wm.open_mainfile(filepath=legacy)
assert all(s.mixie_chat_user_id == 'reader@example.invalid' for s in bpy.data.scenes)
assert all(not s.is_property_set('mixie_chat_user_id') for s in bpy.data.scenes)
bpy.context.window_manager.mixie_chat_is_logged_in = True
bpy.context.window_manager.mixar_account_name = 'Reader'
result = True
""")
    qa.step('profile', qa.click, text='reader@example.invalid', area_type='TOPBAR')
    path = qa.eval("import os; result=os.path.join(os.environ['MIXAR_QA_OUT'], 'identity-profile.png')")
    qa.step('profile_snap', qa.cmd, 'snap', path=path)
    qa.press('ESC')
    qa.step('scene_switch_logout_and_save', qa.eval, """
import os
from mixar.modules.space_mixie_chat.core import account_identity as identity
bpy.context.window.scene = bpy.data.scenes['QA Other Scene']
assert bpy.context.scene.mixie_chat_user_id == 'reader@example.invalid'
bpy.ops.mixie_chat.logout()
assert all(s.mixie_chat_user_id == '' for s in bpy.data.scenes)
bpy.context.scene.mixie_chat_user_id = 'next@example.invalid'
assert all(s.mixie_chat_user_id == 'next@example.invalid' for s in bpy.data.scenes)
clean = os.path.join(os.environ['MIXAR_QA_OUT'], 'identity-clean.blend')
bpy.ops.wm.save_as_mainfile(filepath=clean)
# Read with the old RNA definition to detect any persisted email, without
# the migration handlers or runtime getter masking leaked file contents.
identity.unregister()
bpy.types.Scene.mixie_chat_user_id = bpy.props.StringProperty(options={'SKIP_SAVE'})
try:
    bpy.ops.wm.open_mainfile(filepath=clean)
    assert all(s.mixie_chat_user_id == '' for s in bpy.data.scenes)
finally:
    identity.register()
bpy.ops.wm.open_mainfile(filepath=os.path.join(os.environ['MIXAR_QA_OUT'], 'identity-legacy.blend'))
assert all(s.mixie_chat_user_id == '' for s in bpy.data.scenes)
result = True
""")
    return {'profile': path, 'legacy_load': True, 'all_scenes': True, 'no_saved_email': True}


if __name__ == '__main__':
    run_scenario('profile_identity', run)
