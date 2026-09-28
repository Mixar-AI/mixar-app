#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Replay after moodboard_sharing_e2e in the isolated app + disposable API.

Uses only synthetic source in QA_SCENARIO_OUT. Publishes through native controls,
downloads through the file picker and proves no code was enabled or executed.
"""
import os
from pathlib import Path
import sys
import time
import zipfile

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/community-qa'))
S = 'drv.main_window().scene'
WM = 'bpy.context.window_manager'


def snap(qa, name):
    time.sleep(.8)
    qa.snap(str(OUT / (name + '.png')))


def setup(qa):
    if qa.find(area_type='FILE_BROWSER')['total']:
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_cancel')
    if qa.find(popup=True)['total']:
        qa.press('ESC')
    root = OUT / 'addons'
    package = root / 'quick_layout'
    package.mkdir(parents=True, exist_ok=True)
    (package / '__init__.py').write_text("bl_info={'name':'Quick Layout','description':'Arrange objects into clean grids in one click.','version':(1,0,0)}\nraise RuntimeError('QA: shared code must not execute')\n")
    (package / 'README.md').write_text('Quick Layout\nSelect your objects and choose the layout tool.\n')
    (package / '.env').write_text('QA_PRIVATE_SENTINEL=not-for-sharing\n')
    other = root / 'private_tool';other.mkdir(exist_ok=True)
    (other / '__init__.py').write_text('private = True\n')
    qa.eval(f'''
import os
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.addon_project.service import get_addon_project_service
from mixar.modules.addon_project.manifest import mark_workspace_manifest
service=get_addon_project_service()
linked=service.link({str(root)!r},entrypoint='quick_layout')
mark_workspace_manifest(__import__('pathlib').Path({str(root)!r}))
{S}.mixie_addon_project_id=linked['project_id']
bpy.app.driver_namespace['_qa_moodboard_actor']['name']='owner'
{WM}.mixie_chat_is_logged_in=True
{S}.mixie_chat_user_id='a1111111-1111-4111-8111-111111111111'
from mixar.modules.moodboard.core import sharing_flow
sharing_flow.reset()
result=True
''')


def publish(qa):
    qa.click(text='Community', but_type='Pulldown')
    qa.click(op='MIXAR_OT_addon_share', popup=True)
    qa.wait(f'bool({WM}.community_addon_module)', timeout=10)
    snap(qa, '08-addon-publish')
    qa.cmd('choose', widget={'popup':True,'prop':'community_addon_visibility'}, item='Public in Explore')
    qa.click(op='MIXAR_OT_addon_publish', popup=True)
    qa.wait(f'"Add-on published" in {WM}.moodboard_community_notice and not {WM}.moodboard_community_busy',timeout=20)
    link=qa.eval(f'result={WM}.moodboard_community_link')
    snap(qa, '09-addon-published')
    qa.press('ESC')
    return link


def discover_download(qa):
    qa.eval(f'''
bpy.app.driver_namespace['_qa_moodboard_actor']['name']='viewer'
{S}.mixie_chat_user_id='b2222222-2222-4222-8222-222222222222'
from mixar.modules.moodboard.core import sharing_flow
sharing_flow.reset()
result=True
''')
    qa.click(text='Community', but_type='Pulldown')
    qa.click(op='MIXIE_OT_moodboard_explore', popup=True, text='Explore Add-ons')
    qa.wait(f'not {WM}.moodboard_community_busy', timeout=15)
    qa.wait("bool(drv.find(text='Quick Layout', popup=True))", timeout=5)
    assert qa.find(text='Quick Layout', popup=True)['total'] == 1
    snap(qa, '10-addon-explore')
    qa.click(op='MIXIE_OT_moodboard_community_action', popup=True, text='Details')
    qa.wait(f'{WM}.moodboard_community_selected==0',timeout=5)
    assert qa.find(text='Delete', popup=True)['total'] == 0
    snap(qa, '11-addon-details')
    qa.click(op='MIXAR_OT_community_download', popup=True)
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='directory'))",timeout=8)
    destination=OUT/'downloaded-quick-layout.zip'
    if destination.exists():destination.unlink()
    qa.eval("h=drv.find(area_type='FILE_BROWSER',prop='directory')[0]\n"
            "p=h['_area'].spaces.active.params\n"
            f"p.directory={str(OUT).encode()!r}\np.filename={destination.name!r}\nresult=True")
    qa.click(area_type='FILE_BROWSER',op='FILE_OT_execute')
    qa.wait(f'not {WM}.moodboard_community_busy and "ZIP downloaded" in {WM}.moodboard_community_notice',timeout=20)
    assert destination.exists()
    with zipfile.ZipFile(destination) as package:
        assert set(package.namelist()) == {'quick_layout/__init__.py','quick_layout/README.md'}
        assert b'must not execute' in package.read('quick_layout/__init__.py')
    qa.eval("assert 'quick_layout' not in __import__('sys').modules;result=True")
    snap(qa, '12-addon-downloaded')
    qa.press('ESC')
    return True


def revoke(qa, link):
    from urllib.error import HTTPError
    from urllib.request import urlopen
    qa.eval(f"bpy.app.driver_namespace['_qa_moodboard_actor']['name']='owner';{S}.mixie_chat_user_id='a1111111-1111-4111-8111-111111111111';result=True")
    qa.click(text='Community', but_type='Pulldown')
    qa.click(op='MIXIE_OT_moodboard_explore', popup=True, text='Explore Add-ons')
    qa.wait(f'not {WM}.moodboard_community_busy',timeout=15)
    qa.click(op='MIXIE_OT_moodboard_explore_load',popup=True,text='My Library')
    qa.wait(f'not {WM}.moodboard_community_busy',timeout=15)
    qa.click(op='MIXIE_OT_moodboard_community_action',popup=True,text='Details')
    qa.click(op='MIXIE_OT_moodboard_community_action',popup=True,text='Make Private')
    qa.wait(f'not {WM}.moodboard_community_busy and "Now private" in {WM}.moodboard_community_notice',timeout=15)
    try:
        urlopen(link+'/download')
        raise AssertionError('Revoked download still works')
    except HTTPError as exc:
        assert exc.code==404
    snap(qa, '13-addon-revoked')
    qa.press('ESC')
    return True


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.step('prepare_synthetic_source',setup,qa)
    link=qa.step('publish_from_community_menu',publish,qa)
    qa.step('second_user_downloads_without_execution',discover_download,qa)
    qa.step('owner_revokes_download',revoke,qa,link)
    return {'paid_requests':0,'code_executed':False,'screenshots':str(OUT)}


if __name__=='__main__':run_scenario('community_addons_e2e',run)
