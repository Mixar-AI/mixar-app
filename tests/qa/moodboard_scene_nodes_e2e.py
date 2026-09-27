#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit native Scene-node navigation, refresh, duplication and persistence.

Run only in an isolated MIXAR_QA app. Uses QA_HARNESS and MIXAR_QA_PORT.
"""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/moodboard-sharing-qa'))
S = 'drv.main_window().scene'


def menu(qa):
    qa.eval("""
w=drv.main_window();a=next(a for a in w.screen.areas if a.type=='MIXIE')
r=next(r for r in a.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=w,area=a,region=r):
    bpy.ops.wm.call_menu(name='MIXIE_MT_moodboard_context_menu')
result=True
""")


def setup(qa):
    qa.eval("""
import os
assert os.environ.get('MIXAR_QA')=='1'
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import switch_scene_tab,inherit_account,inherit_settings
w=drv.main_window();source=w.scene
source.name='QA Source Scene'
board=bpy.data.scenes.new('QA Scene Node Board')
inherit_account(source,board);inherit_settings(source,board)
switch_scene_tab(board,was=source)
result=True
""")


def add_and_duplicate(qa):
    qa.click(text='Start with an editable node template',area_type='MIXIE')
    qa.click(op='MIXIE_OT_moodboard_add_scene',popup=True)
    qa.cmd('set_text',widget={'popup':True,'prop':'scene_name'},text='QA Source Scene',enter=False)
    qa.click(text='Right-click the node to open its scene.',popup=True,but_type='Label')
    qa.click(text='Add Scene',popup=True,but_type='But')
    qa.wait(f'len({S}.mixie_moodboard_images)==1',timeout=10)
    qa.eval(f"assert {S}.mixie_moodboard_images[0].source_scene.name=='QA Source Scene';result=True")
    menu(qa)
    qa.click(op='MIXIE_OT_moodboard_duplicate',popup=True)
    qa.press('ESC')  # keep duplicate at its original position, cancel only its move
    qa.eval(f"assert len({S}.mixie_moodboard_images)==2;assert all(i.source_scene.name=='QA Source Scene' and i.scene_node for i in {S}.mixie_moodboard_images);result=True")
    qa.eval("bpy.data.scenes['QA Source Scene'].name='QA Renamed Source';result=True")
    menu(qa)
    qa.click(op='MIXIE_OT_moodboard_refresh_scene',popup=True)
    qa.eval(f"assert next(i for i in {S}.mixie_moodboard_images if i.selected).scene_title=='QA Renamed Source';result=True")
    menu(qa)
    qa.snap(str(OUT/'06-scene-menu.png'))
    qa.click(op='MIXIE_OT_moodboard_open_scene',popup=True)
    qa.wait(f'{S}.name=="QA Renamed Source"',timeout=10)
    return True


def persistence_and_missing_source(qa):
    path=str(OUT/'scene-nodes.mixar')
    qa.eval(f"bpy.ops.wm.save_as_mainfile(filepath={path!r});result=True")
    qa.eval(f"bpy.ops.wm.open_mainfile(filepath={path!r});result=True")
    qa.wait("bpy.data.scenes.get('QA Scene Node Board') is not None",timeout=15)
    qa.eval("""
from mixar.modules.space_mixie_chat.ui.operators.scene_tab_ops import switch_scene_tab
board=bpy.data.scenes['QA Scene Node Board']
assert all(i.scene_node and i.source_scene.name=='QA Renamed Source' and (i.image.packed_file or i.image.source=='GENERATED') for i in board.mixie_moodboard_images)
switch_scene_tab(board,was=drv.main_window().scene)
bpy.data.scenes.remove(bpy.data.scenes['QA Renamed Source'])
assert all(i.source_scene is None and i.image for i in board.mixie_moodboard_images)
result=True
""")
    menu(qa)
    assert qa.find(op='MIXIE_OT_moodboard_open_scene',popup=True)['total']==0
    assert qa.find(text='Scene preview; source is not in this project',popup=True)['total']==1
    qa.snap(str(OUT/'07-missing-scene.png'))
    qa.press('ESC')
    return True


def run(qa):
    OUT.mkdir(parents=True,exist_ok=True)
    qa.step('prepare_scene_fixture',setup,qa)
    qa.step('add_duplicate_refresh_open',add_and_duplicate,qa)
    qa.step('save_reload_and_deleted_source',persistence_and_missing_source,qa)
    return {'paid_requests':0,'screenshots':str(OUT)}


if __name__=='__main__':
    run_scenario('moodboard_scene_nodes_e2e',run)
