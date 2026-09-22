#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Shared canvas/template replay. Requires an isolated, logged-in Dev QA app.

Set QA_HARNESS, MIXAR_QA_PORT and QA_SCENARIO_OUT. Start with reset-state.
Templates, menus, resizing and settings use native events. Eval only reads
state and sets the editor/scale fixtures. Inspect the screenshots as well as
the verdict. This scenario never presses Generate.
"""

import json
import textwrap
import time

from moodboard_drawer_e2e import (
    OUT, SCENE, geometry, require, run_scenario, target, toggle,
)
from moodboard_drawer_tools_e2e import resize, toolbar
from moodboard_node_layout_e2e import settings_edit_reset

TEMPLATES = {'text': 'Start with an editable node template'}
ADD = 'MIXIE_OT_moodboard_add_template'
BOARD = {'text': 'Arrange, frame, or clear the board'}
KINDS = ('IMAGE_GEN', 'MODEL_3D', 'VIDEO_GEN')
LABELS = ('Generate Image', 'Image to 3D', 'Video Generation')


def snapshot(qa, name, area='VIEW_3D'):
    time.sleep(.3)
    return qa.cmd('snap', path=str(OUT / f'{name}.png'), area=area)


def nodes(qa):
    return qa.eval(f"""
result=[{{'id':n.node_id,'type':n.action_type,'state':n.state,
         'model':n.model,'job_id':n.job_id,
         'rect':[n.position_x,n.position_y,n.width,n.height]}}
        for n in {SCENE}.mixie_moodboard_action_nodes]
""")


def parameter_info(qa):
    qa.click(op='MIXIE_OT_moodboard_node_settings', region_type='TOOL_PROPS')
    label = qa.eval(f"result=next(p.label or p.name "
                    f"for n in {SCENE}.mixie_moodboard_action_nodes "
                    f"if n.node_id=={SCENE}.mixie_moodboard_active_node_id "
                    "for p in n.parameters if p.visible)")
    expected = textwrap.wrap(label, width=45)[0]
    before = nodes(qa)
    # Native buttons sharing one operator have no exported collection index.
    # Resolve the first catalog field from the live semantic result's bounds.
    item = qa.find(popup=True, op='MIXIE_OT_moodboard_parameter_info')['widgets'][0]
    qa.cmd('click_xy', x=item['center'][0], y=item['center'][1])
    qa.wait(f'bool(drv.find(popup=True,text={expected!r}))', timeout=4)
    snapshot(qa, '09_parameter_help')
    require(nodes(qa) == before, 'Reading parameter help changed the graph')
    qa.press('ESC')
    if qa.find(popup=True)['total']:
        qa.press('ESC')


def menu(qa, region='TOOL_PROPS'):
    qa.click(**TEMPLATES, region_type=region)
    qa.wait(f"len(drv.find(popup=True,op='{ADD}')) >= 3", timeout=4)
    items = qa.find(popup=True, op=ADD)['widgets']
    require(all(any(w['text'] == name and w['enabled'] for w in items)
                for name in LABELS), 'Live catalog lacks the three starter templates')
    require(all(w['mixar_theme'] == 'ZEN' and w['mixar_component'] == 'action'
                for w in items), 'Template menu bypassed shared components')
    return items


def add(qa, label, kind, popup=True):
    before = nodes(qa)
    qa.click(op=ADD, text=label, popup=popup)
    qa.wait(f'len({SCENE}.mixie_moodboard_action_nodes)=={len(before)+1}', timeout=5)
    after = nodes(qa)
    node = after[-1]
    require(node['type'] == kind and node['state'] == 'DRAFT' and not node['job_id'],
            f'Template did not create an idle draft: {node}')
    require(node['model'], 'Template did not initialize its catalog model')
    require(qa.eval(f'result={SCENE}.mixie_moodboard_active_node_id') == node['id'],
            'New template did not become active')
    for old in before:
        ax, ay, aw, ah = old['rect']
        bx, by, bw, bh = node['rect']
        require(ax+aw <= bx or bx+bw <= ax or ay+ah <= by or by+bh <= ay,
                'Templates overlap at creation')
    return node['id']


def shortcuts(qa, region='TOOL_PROPS'):
    items = qa.find(op=ADD, region_type=region, limit=100)['widgets']
    required = ['Add Mesh', *LABELS]
    # Wide hosts can reveal further catalog templates; the drag fixtures
    # require these leading actions, not a fixed total number of shortcuts.
    require([w['text'] for w in items[:len(required)]] == required,
            f'Wrong shortcut strip: {items}')
    require(all(item['enabled'] for item in items[:len(required)]),
            'A required template is unavailable in the QA catalog')
    for item in items:
        require(item['mixar_theme'] == 'ZEN' and
                item['mixar_component'] == 'action', f'Unstyled shortcut: {item}')
    for first, second in zip(items, items[1:]):
        require(first['rect'][2] <= second['rect'][0], 'Template buttons overlap')
    return items


def framed(qa, host):
    """Read complete card geometry, including portions hidden by a sidebar."""
    state = qa.eval(f"""
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=={host!r})
kind='TOOL_PROPS' if area.type=='VIEW_3D' else 'WINDOW'
region=next(r for r in area.regions if r.type==kind)
rects=[]
for n in win.scene.mixie_moodboard_action_nodes:
    a=region.view2d.view_to_region(n.position_x,n.position_y,clip=False)
    b=region.view2d.view_to_region(n.position_x+n.width,n.position_y+n.height,clip=False)
    rects.append([a[0]+region.x,a[1]+region.y,b[0]+region.x,b[1]+region.y])
sidebar=next((r for r in area.regions if r.type=='UI' and r.width>1),None)
result={{'rects':rects,'bottom':region.y,
         'right':sidebar.x if sidebar and area.type=='MIXIE' else region.x+region.width,
         'scale':bpy.context.preferences.system.ui_scale}}
""")
    tools = qa.find(area_type=host, op='MIXIE_OT_moodboard_add_textbox')['widgets'][0]
    strip = shortcuts(qa, 'WINDOW' if host == 'MIXIE' else 'TOOL_PROPS')
    for rect in state['rects']:
        require(rect[0] > tools['rect'][2] and rect[2] < state['right'] and
                rect[1] > state['bottom'] and rect[3] < strip[0]['rect'][1],
                f'Frame All hides a card beneath canvas chrome: {rect}, {state}')
    return state


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    require(qa.eval("result=__import__('os').environ.get('MIXAR_QA')=='1'"),
            'Use an isolated QA instance')
    qa.cmd('wait_login', timeout=90)
    qa.wait("__import__('mixar.bootstrap.generation_catalog_cache',"
            "fromlist=['is_loaded']).is_loaded()", timeout=45)
    require(not nodes(qa), 'Use reset-state before this replay')
    if geometry(qa)['workspace'] != 'Zen Mode':
        qa.click(area_type='TOPBAR', op='MIXAR_OT_set_ui_mode_ai')
    if geometry(qa)['amount'] < .02:
        toggle(qa, 1)
    original = geometry(qa)
    resize(qa, 340)
    qa.step('shared_toolbar', toolbar, qa)
    qa.step('empty_default', snapshot, qa, '01_empty_default')
    qa.step('minimum_width', resize, qa, 125)
    qa.step('minimum_menu', menu, qa)
    qa.step('minimum_menu_snapshot', snapshot, qa, '02_minimum_menu')
    qa.press('ESC')
    resize(qa, 340)
    menu(qa)
    node_id = qa.step('image_template', add, qa, LABELS[0], KINDS[0])
    qa.step('draft_snapshot', snapshot, qa, '03_image_draft')
    qa.step('catalog_settings_edit_clamp_reset', settings_edit_reset, qa, node_id)
    qa.step('catalog_parameter_help', parameter_info, qa)
    qa.step('wide_drawer', resize, qa, 850)
    qa.step('wide_shortcuts', shortcuts, qa)
    qa.step('wide_snapshot', snapshot, qa, '04_wide_shortcuts')
    qa.step('model_template', add, qa, LABELS[1], KINDS[1], False)
    qa.step('video_template', add, qa, LABELS[2], KINDS[2], False)
    qa.click(**BOARD, region_type='TOOL_PROPS')
    qa.click(op='MIXIE_OT_moodboard_frame', popup=True)
    qa.step('drawer_frame_reserves_chrome', framed, qa, 'VIEW_3D')
    qa.step('populated_snapshot', snapshot, qa, '05_three_templates')
    scale = qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        qa.eval('bpy.context.preferences.view.ui_scale=1.25; result=True')
        time.sleep(.5)
        qa.step('scaled_shortcuts', shortcuts, qa)
        qa.step('scaled_snapshot', snapshot, qa, '06_scale125')
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
        time.sleep(.5)
    records = nodes(qa)
    require(all(n['state'] == 'DRAFT' and not n['job_id'] for n in records),
            'A template submitted generation')
    final = geometry(qa)
    require(original['objects'] == final['objects'] and original['view'] == final['view']
            and original['viewport'] == final['viewport'], 'Canvas changed the 3D viewport')
    # Swap the host fixture: board data and shared native blocks must survive.
    qa.eval("win=drv.main_window()\n"
            "area=next(a for a in win.screen.areas if a.type=='VIEW_3D')\n"
            "area.type='MIXIE'\nresult=True")
    qa.wait("bool(drv.find(area_type='MIXIE',op='"+ADD+"'))", timeout=10)
    qa.step('editor_shortcuts', shortcuts, qa, 'WINDOW')
    require(nodes(qa) == records, 'Changing canvas hosts altered the graph')
    tools = qa.find(area_type='MIXIE', op='MIXIE_OT_moodboard_add_textbox')['widgets']
    require(len(tools) == 1 and tools[0]['block'] == 'MIXIE_PT_canvas_tools',
            'Editor duplicated the toolbar')
    qa.step('editor_menu', menu, qa, 'WINDOW')
    qa.step('editor_menu_snapshot', snapshot, qa, '07_editor_menu', 'MIXIE')
    qa.press('ESC')
    qa.click(**BOARD, region_type='WINDOW')
    qa.click(op='MIXIE_OT_moodboard_frame', popup=True)
    qa.step('editor_frame_reserves_chrome', framed, qa, 'MIXIE')
    qa.step('editor_snapshot', snapshot, qa, '08_editor', 'MIXIE')
    result = {'backend_submissions': 0, 'nodes': records, 'shared_hosts': True,
              'widths': [125, 340, 850], 'ui_scales': [1, 1.25]}
    (OUT / 'state-evidence.json').write_text(json.dumps(result, indent=2))
    return result


if __name__ == '__main__':
    run_scenario('moodboard_redesign_e2e', run)
