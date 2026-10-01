#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native folder picker/removal plus chat/input snapshot regression.

Run against an isolated QA app with QA_HARNESS, MIXAR_QA_PORT and
QA_SCENARIO_OUT. Only the final outgoing command is intercepted. Backend
resume/replay semantics are covered by the backend's graph regression tests.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from generation_reference_column_e2e import capture, pause

SETUP = r'''
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from mixar.modules.space_mixie_chat.core import turn_transport
assert os.environ.get('MIXAR_QA') == '1'
f = drv._folder_qa = SimpleNamespace(scene=drv.main_window().scene,
    scratch=tempfile.TemporaryDirectory(prefix='folder-resume-'),
    original_command=turn_transport.command, calls=[])
assert not len(f.scene.mixie_context_folders)
f.old_session = f.scene.mixie_session_id
f.scene.mixie_session_id = 'qa-folder-resume'
f.empty = Path(f.scratch.name) / 'New Folder'
f.hero = Path(f.scratch.name) / '01-Hero-Project'
f.empty.mkdir()
f.hero.mkdir()
(f.hero / 'README.md').write_text('Lantern Plaza')
turn_transport.command = lambda method, payload, *a, **kw: f.calls.append((method, payload))
f.handler = turn_transport.TurnTransport(f.scene.name)
result = {'empty': str(f.empty), 'hero': str(f.hero)}
'''


def pick(qa, directory):
    qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_attach')
    qa.wait("bool(drv.find(op='MIXIE_CHAT_OT_add_context_folder', popup=True))", timeout=5)
    qa.click(op='MIXIE_CHAT_OT_add_context_folder', popup=True)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))", timeout=8)
    qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
            "p=h['_area'].spaces.active.params\n"
            f"p.directory={str(directory).encode()!r}\nresult=True")
    pause(qa)
    qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')
    qa.wait("not drv.find(area_type='FILE_BROWSER')", timeout=8)
    qa.wait('len(drv._folder_qa.scene.mixie_context_folders)==1', timeout=5)


def remove(qa):
    qa.click(area_type='AGENT_BUBBLE', op='MIXIE_CHAT_OT_remove_context_folder')
    qa.wait('len(drv._folder_qa.scene.mixie_context_folders)==0', timeout=5)


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/folder-resume-qa'))
    out.mkdir(parents=True, exist_ok=True)
    qa.wait("bpy.types.Operator.bl_rna_get_subclass_py('MIXIE_CHAT_OT_add_context_folder') is not None",
            timeout=30)
    qa.open_chat()
    paths = qa.step('isolated_fixture', qa.eval, SETUP)
    try:
        qa.step('attach_empty_via_picker', pick, qa, paths['empty'])
        qa.eval("f=drv._folder_qa\n"
                "assert f.handler.start_stream('Create a character','qa-instance','qa-folder-resume')\n"
                "assert f.calls[-1][1]['folder_context']['folders'][0]['file_count']==0\n"
                "f.old_id=f.scene.mixie_context_folders[0].folder_id\nresult=True")
        capture(qa, out, 'before-empty-folder')
        qa.step('remove_old_folder', remove, qa)
        qa.step('attach_hero_via_picker', pick, qa, paths['hero'])
        capture(qa, out, 'after-hero-folder')
        replacement = qa.step('answer_refreshes_manifest_and_grant', qa.eval, r'''
from mixar.modules.context_folder.core import grants, rpc
f = drv._folder_qa
assert f.handler.start_input_stream('qa-folder-resume','respond',text='Create this')
method, payload = f.calls[-1]
assert method == 'input' and payload['text'] == 'Create this'
folder = payload['folder_context']['folders'][0]
assert folder['name'] == '01-Hero-Project' and folder['file_count'] == 1, folder
assert folder['notes'][0]['excerpt'] == 'Lantern Plaza'
assert not grants.is_granted('qa-folder-resume', f.old_id)
assert grants.is_granted('qa-folder-resume', folder['folder_id'])
reply = rpc.dispatch('context_folder.read', {'session_id': 'qa-folder-resume',
    'folder_id': folder['folder_id'], 'path': 'README.md'})
assert reply['success'] and 'Lantern Plaza' in reply['text'], reply
result = {'folder': folder['name'], 'files': folder['file_count'], 'read': reply['text']}
''')
        qa.step('remove_current_folder', remove, qa)
        qa.step('answer_clears_manifest_and_grant', qa.eval, r'''
from mixar.modules.context_folder.core import grants
f = drv._folder_qa
assert f.handler.start_input_stream('qa-folder-resume','respond',text='Continue')
assert f.calls[-1][1]['folder_context'] == {'version': 1, 'folders': []}
assert not grants.granted('qa-folder-resume')
result = True
''')
        capture(qa, out, 'after-removal')
        return {'passed': True, 'paid_requests': 0, **replacement}
    finally:
        qa.eval(r'''
from mixar.modules.space_mixie_chat.core import turn_transport, turn_events
from mixar.modules.context_folder.core import attach, grants
f = drv._folder_qa
turn_transport.command = f.original_command
turn_events.drop_scene(f.scene.name)
for item in list(f.scene.mixie_context_folders):
    attach.detach_folder(f.scene, item.folder_id)
grants.grant('qa-folder-resume', [])
f.scene.mixie_session_id = f.old_session
f.scratch.cleanup()
del drv._folder_qa
result = True
''')


if __name__ == '__main__':
    run_scenario('context_folder_resume_e2e', run)
