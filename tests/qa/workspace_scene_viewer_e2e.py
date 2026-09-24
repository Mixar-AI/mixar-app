#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit workspace viewer replay against an isolated Dev app.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4789 \
  python3 tests/qa/workspace_scene_viewer_e2e.py

Uses real local scenes, native offscreen renders, and semantic UI clicks.
No model, generation API or network preview is used. Inspect the saved PNGs.
"""
import inspect
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def seed():
    import bpy
    import qa_driver as drv
    from mixar.modules.agent_panel.core.cards import clear_cards, mirror_todo_items
    assert os.environ.get('MIXAR_QA') == '1'
    main = drv.main_window().scene
    assert not main.mixie_chat_is_busy
    main.mixie_session_id = 'viewer-qa-main'
    main.mixie_run_id = 'viewer-qa-run'
    main.mixie_run_open = True
    names = ['Stone pavilion', 'Lighting in main scene', 'Copper towers',
             'Garden walkway', 'Wooden trellis', 'Glass conservatory', 'Sculpture courtyard']
    scenes = []
    for i, name in enumerate(names):
        if i == 1:
            continue
        scene = bpy.data.scenes.new('Viewer QA ' + name)
        scene.mixie_session_id = 'agentlane:viewer-qa-' + str(i)
        scene['mixar_workspace_token'] = 'viewer-qa-' + str(i)
        scene['mixar_workspace_task'] = 'viewer-' + str(i)
        scene['mixar_workspace_run'] = main.mixie_run_id
        scene['mixar_workspace_main_session'] = main.mixie_session_id
        scenes.append(scene.name)
        material = bpy.data.materials.new('Viewer QA Material '+str(i))
        material.diffuse_color = ((.6,.38,.16,1) if i == 2 else (.25,.5,.4,1))
        for j in range(9):
            mesh = bpy.data.meshes.new('Viewer QA Mesh')
            verts = [(x,y,z) for z in (0,1) for y in (-.6,.6) for x in (-.6,.6)]
            mesh.from_pydata(verts, [], [(0,1,3,2),(4,6,7,5),(0,4,5,1),
                                       (2,3,7,6),(0,2,6,4),(1,5,7,3)])
            obj = bpy.data.objects.new('Viewer QA Block '+str(i)+'-'+str(j), mesh)
            scene.collection.objects.link(obj)
            obj.location = ((j%3)*2, (j//3)*2, 0)
            obj.scale.z = (j%3+1)*(.8 if i == 0 else 1.4)
            obj.data.materials.append(material)
    # An ordinary scene and a stale run with the MAIN task ID must never create an eye.
    other = bpy.data.scenes.new('Viewer QA unrelated')
    other['mixar_workspace_task'] = 'viewer-1'
    stale = bpy.data.scenes.new('Viewer QA stale')
    for key, value in bpy.data.scenes[scenes[0]].items():
        stale[key] = value
    stale.mixie_session_id = 'agentlane:viewer-qa-stale'
    stale['mixar_workspace_token'] = 'viewer-qa-stale'
    stale['mixar_workspace_task'] = 'viewer-1'
    stale['mixar_workspace_run'] = 'previous-run'
    clear_cards()
    mirror_todo_items([{'id': 'viewer-'+str(i), 'text': name, 'status': 'in_progress'}
                       for i,name in enumerate(names)])
    return {'main': main.name, 'scenes': scenes}


def run(qa):
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/workspace-viewer-qa')).resolve()
    out.mkdir(parents=True, exist_ok=True)
    qa.dismiss_splash()
    qa.wait("hasattr(bpy.context.window_manager,'mixar_agent_cards_active')", timeout=30)
    qa.eval('import os\n' + inspect.getsource(seed) + '\nresult=seed()')
    qa.wait("len(drv.find(surface='agent_panel_eye'))==2", timeout=15)
    qa.eval("def settle():\n    yield 1\n    return True\nresult=settle()")
    qa.step('workspace_eyes_only', qa.eval,
            "result=[t['value'] for t in drv.find(surface='agent_panel_eye')]\n"
            "assert set(result)=={'viewer-0','viewer-2'}")
    qa.snap(str(out/'cards.png'))
    qa.eval("scene=next(s for s in bpy.data.scenes if s.get('mixar_workspace_task')=='viewer-0')\n"
            "duplicate=scene.copy()\nduplicate.name='Viewer QA duplicate'\nresult=True")
    qa.wait("all(t['value']!='viewer-0' for t in drv.find(surface='agent_panel_eye'))")
    qa.eval("bpy.data.scenes.remove(bpy.data.scenes['Viewer QA duplicate'])\nresult=True")
    qa.wait("any(t['value']=='viewer-0' for t in drv.find(surface='agent_panel_eye'))")
    # Exercise the actual input-blocking modal while work is running.
    qa.eval("import mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op as lock\n"
            "bpy.app.driver_namespace['viewer_qa_lock_probe']=lock.is_agent_executing\n"
            "lock.is_agent_executing=lambda: True\n"
            "win=drv.main_window()\narea=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
            "with bpy.context.temp_override(window=win,area=area):\n"
            "    bpy.ops.mixar.agent_viewport_block('INVOKE_DEFAULT')")
    qa.step('open_from_eye_while_locked', qa.click, surface='agent_panel_eye', value='viewer-0')
    qa.wait("any(t['text']=='viewer-0' and t['value']!='unavailable' "
            "for t in drv.find(surface='workspace_viewer_scene'))", timeout=20)
    qa.eval("assert not drv.find(surface='agent_panel_eye')\nresult=True")
    qa.snap(str(out/'pavilion.png'))
    frame = qa.eval("result=int(drv.find(surface='workspace_viewer_scene')[0]['value'])")
    qa.eval("bpy.data.objects['Viewer QA Block 0-0'].scale.z=6")
    qa.wait(f"int(drv.find(surface='workspace_viewer_scene')[0]['value'])>{frame}", timeout=10)
    qa.snap(str(out/'pavilion-updated.png'))
    qa.step('main_scene_unchanged', qa.eval,
            "assert drv.main_window().scene.mixie_session_id=='viewer-qa-main'\nresult=True")
    # Reverse the modal-handler order: a newly started lock must still let
    # the read-only viewer receive input.
    qa.eval("import mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op as lock\n"
            "lock.is_agent_executing=lambda: False\n"
            "def settle():\n    yield .3\n    return True\nresult=settle()")
    qa.eval("import mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op as lock\n"
            "lock.is_agent_executing=lambda: True\n"
            "win=drv.main_window()\narea=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
            "with bpy.context.temp_override(window=win,area=area):\n"
            "    bpy.ops.mixar.agent_viewport_block('INVOKE_DEFAULT')")
    qa.step('main_task_not_switchable', qa.click, surface='workspace_viewer_agent', text='viewer-1')
    qa.eval("assert drv.find(surface='workspace_viewer_scene')[0]['text']=='viewer-0'\nresult=True")
    qa.step('scroll_to_other_agents', qa.click, surface='workspace_viewer_next')
    qa.wait("any(t['text']=='viewer-2' for t in drv.find(surface='workspace_viewer_agent'))")
    qa.step('switch_workspace', qa.click, surface='workspace_viewer_agent', text='viewer-2')
    qa.wait("any(t['text']=='viewer-2' and t['value']!='unavailable' "
            "for t in drv.find(surface='workspace_viewer_scene'))", timeout=10)
    qa.snap(str(out/'towers.png'))
    for _ in range(5):
        qa.click(surface='workspace_viewer_next')
    qa.step('last_agent_reachable', qa.click, surface='workspace_viewer_agent', text='viewer-6')
    qa.wait("any(t['text']=='viewer-6' and t['value']!='unavailable' "
            "for t in drv.find(surface='workspace_viewer_scene'))")
    qa.snap(str(out/'last-agent.png'))
    for _ in range(5):
        qa.click(surface='workspace_viewer_previous')
    qa.click(surface='workspace_viewer_agent', text='viewer-2')
    qa.wait("drv.find(surface='workspace_viewer_scene')[0]['text']=='viewer-2'")
    qa.step('removed_workspace_is_not_live', qa.eval,
            "scene=next(s for s in bpy.data.scenes if s.get('mixar_workspace_task')=='viewer-2')\n"
            "bpy.data.scenes.remove(scene)\nresult=True")
    qa.wait("drv.find(surface='workspace_viewer_scene')[0]['value']=='unavailable'")
    qa.snap(str(out/'workspace-ended.png'))
    qa.step('close', qa.click, surface='workspace_viewer_close')
    qa.wait("not drv.find(surface='workspace_viewer_scene')")
    qa.step('reopen', qa.click, surface='agent_panel_eye', value='viewer-0')
    qa.wait("bool(drv.find(surface='workspace_viewer_scene'))")
    # The viewer is a window-level modal: it must claim only its own viewport
    # region. A press on the Moodboard grip (an overlapping TOOL_PROPS region)
    # reaches the drawer, which opens while the preview stays up.
    grip = qa.find(surface='moodboard_drawer_grip')
    drawer_checked = bool(grip)
    if grip:
        gx, gy = ((grip[0]['rect'][0] + grip[0]['rect'][2]) // 2,
                  (grip[0]['rect'][1] + grip[0]['rect'][3]) // 2)
        qa.step('drawer_opens_over_viewer', qa.cmd, 'click_xy', x=gx, y=gy)
        qa.wait("bpy.context.window_manager.mixar_moodboard_drawer_amount>0.5", timeout=10)
        qa.eval("assert drv.find(surface='workspace_viewer_scene')\nresult=True")
        qa.snap(str(out/'drawer-over-viewer.png'))
        grip = qa.find(surface='moodboard_drawer_grip')
        gx, gy = ((grip[0]['rect'][0] + grip[0]['rect'][2]) // 2,
                  (grip[0]['rect'][1] + grip[0]['rect'][3]) // 2)
        qa.cmd('click_xy', x=gx, y=gy)
        qa.wait("bpy.context.window_manager.mixar_moodboard_drawer_amount<0.02", timeout=10)
        qa.eval("assert drv.find(surface='workspace_viewer_scene')\nresult=True")
    # A click on the viewport outside the preview and its agent bar dismisses
    # the viewer, so a covered close button can never strand the user.
    image = qa.find(surface='workspace_viewer_scene')[0]['rect']
    qa.step('outside_click_closes', qa.cmd, 'click_xy', x=image[0] - 30, y=image[1] + 10)
    qa.wait("not drv.find(surface='workspace_viewer_scene')")
    qa.click(surface='agent_panel_eye', value='viewer-0')
    qa.wait("bool(drv.find(surface='workspace_viewer_scene'))")
    qa.step('escape', qa.press, 'ESC')
    qa.wait("not drv.find(surface='workspace_viewer_scene')")
    qa.click(surface='agent_panel_eye', value='viewer-0')
    qa.wait("bool(drv.find(surface='workspace_viewer_scene'))")
    qa.step('new_run_closes_preview', qa.eval,
            "drv.main_window().scene.mixie_run_id='next-run'\nresult=True")
    qa.wait("not drv.find(surface='workspace_viewer_scene')")
    qa.eval("import mixar.modules.agent_viewport_lock.ui.operators.viewport_block_op as lock\n"
            "lock.is_agent_executing=bpy.app.driver_namespace.pop('viewer_qa_lock_probe')\n"
            "from mixar.modules.agent_panel.core.cards import clear_cards\nclear_cards()\n"
            "main=drv.main_window().scene\nmain.mixie_run_open=False\nmain.mixie_run_id=''\n"
            "main.mixie_session_id=''\n"
            "for s in list(bpy.data.scenes):\n"
            "    if s.name.startswith('Viewer QA'): bpy.data.scenes.remove(s)\nresult=True")
    return {'paid_requests': 0, 'live_updates': True, 'switching': True,
            'workspace_only': True, 'locked_viewport': True, 'deletion': True,
            'escape': True, 'outside_click': True, 'drawer_pass_through': drawer_checked,
            'new_run_cleanup': True, 'screenshots': str(out)}


if __name__ == '__main__':
    run_scenario('workspace_scene_viewer', run)
