#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit real UI sky toggle/settings/HDRI import, cancel, undo and scale replay."""
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario
from zen_scene_toolbar_e2e import HEADER, SETUP, reset_zen_scene

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-sky-controls'))
NODES = SETUP + '\nfrom mixar.modules.workflow.core.zen_sky_lighting import sky_nodes, uses_hdri\nnodes=sky_nodes(scene)\n'


def snap(qa, name):
    qa.cmd('snap', path=str(OUT / (name + '.png')))


def toggle(qa, enabled):
    qa.click(**HEADER, op='MIXAR_OT_zen_set_sky')
    qa.wait(f"(drv.main_window().scene.world == drv.main_window().scene.mixar_zen_sky.sky_world) == {enabled}", timeout=8)
    widget = qa.find(**HEADER, op='MIXAR_OT_zen_set_sky')['widgets'][0]
    assert widget['text'] == ('ON' if enabled else 'OFF'), widget


def set_socket(qa, index, value):
    # Native sockets do not export a custom target index. Select the visible
    # ordered field, then target its current text for the real edit.
    fields=sorted(qa.find(popup=True,prop='default_value')['widgets'],
                  key=lambda w:-w['rect'][1])
    qa.cmd('set_text',widget={'popup':True,'prop':'default_value',
                             'text':fields[index]['text']},text=value)


def file_picker(qa, path=None):
    qa.click(**HEADER, op='MIXAR_OT_zen_load_hdri')
    qa.wait("bool(drv.find(area_type='FILE_BROWSER', prop='filename'))", timeout=10)
    if path is None:
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_cancel')
    else:
        qa.eval(f"""
h=drv.find(area_type='FILE_BROWSER', prop='directory')[0]
params=h['_area'].spaces.active.params
params.directory={str(path.parent).encode()!r}
params.filename={path.name!r}
result=True
""")
        qa.click(area_type='FILE_BROWSER', prop='directory')
        window=qa.find(area_type='FILE_BROWSER', prop='directory')['widgets'][0]['window']
        qa.press('RET', window=window)
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')
    qa.wait("not any(a.type == 'FILE_BROWSER' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=12)


def run(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    reset_zen_scene(qa)
    qa.eval(SETUP+"scene.render.engine='BLENDER_EEVEE'; result=True")
    original=qa.eval(SETUP+'result=scene.world.name if scene.world else None')
    flags=qa.eval(SETUP+'result=[view.shading.use_scene_world, view.shading.use_scene_world_render]')
    snap(qa, 'off')
    toggle(qa, True)
    qa.click(**HEADER, text='Sky Light')
    set_socket(qa,0,'2.5')
    qa.cmd('set_text', widget={'popup':True,'prop':'sun_elevation'}, text='35')
    qa.cmd('set_text', widget={'popup':True,'prop':'sun_rotation'}, text='60')
    values=qa.eval(NODES+"result=[nodes['ShaderNodeBackground'].inputs['Strength'].default_value, nodes['ShaderNodeTexSky'].sun_elevation, nodes['ShaderNodeTexSky'].sun_rotation]")
    assert abs(values[0]-2.5)<.01 and abs(values[1]-.610865)<.01 and abs(values[2]-1.047198)<.01, values
    snap(qa,'sky-properties')
    qa.press('ESC')
    toggle(qa, False)
    assert qa.eval(SETUP+'result=scene.world.name if scene.world else None') == original
    file_picker(qa)
    assert qa.eval(SETUP+'result=scene.world.name if scene.world else None') == original
    # Small synthetic RGBE fixture created only in the scenario output directory.
    path=OUT/'qa-environment.hdr'
    path.write_bytes(b'#?RADIANCE\nFORMAT=32-bit_rle_rgbe\n\n-Y 4 +X 8\n'+bytes([128,160,192,130])*32)
    file_picker(qa,path)
    assert qa.eval(NODES+'result=uses_hdri(scene)')
    assert qa.eval(SETUP+'result=scene.mixar_zen_sky.previous_world.name if scene.mixar_zen_sky.previous_world else None') == original
    qa.click(**HEADER,text='Sky Light')
    set_socket(qa,0,'1.5')
    set_socket(qa,1,'90')
    values=qa.eval(NODES+"result=[nodes['ShaderNodeBackground'].inputs['Strength'].default_value, nodes['ShaderNodeMapping'].inputs['Rotation'].default_value.z]")
    assert abs(values[0]-1.5)<.01 and abs(values[1]-1.570796)<.01,values
    snap(qa,'hdri-properties')
    qa.click(popup=True,op='MIXAR_OT_zen_sky_source',text='Sky')
    assert not qa.eval(NODES+'result=uses_hdri(scene)')
    if not qa.find(popup=True,op='MIXAR_OT_zen_sky_source')['widgets']:
        qa.click(**HEADER,text='Sky Light')
    qa.click(popup=True,op='MIXAR_OT_zen_sky_source',text='HDRI')
    assert qa.eval(NODES+'result=uses_hdri(scene)')
    qa.press('ESC')
    qa.eval(SETUP+"""
def preview():
    view.shading.type='MATERIAL'
    yield 3
    return True
result=preview()
""")
    snap(qa,'hdri-lighting')
    qa.eval(SETUP+"view.shading.type='SOLID'; result=True")
    # A failed decode must retain both world pointers and leak no image or world.
    bad=OUT/'invalid.hdr';bad.write_text('not an image')
    unchanged=qa.eval(NODES+f"""
from mixar.modules.workflow.core.zen_sky_lighting import load_hdri
before=(scene.world,scene.mixar_zen_sky.previous_world,len(bpy.data.worlds),len(bpy.data.images))
try:
    load_hdri(scene,{str(bad)!r})
except (RuntimeError,ValueError):
    pass
else:
    raise AssertionError('Invalid HDRI unexpectedly accepted')
result=before==(scene.world,scene.mixar_zen_sky.previous_world,len(bpy.data.worlds),len(bpy.data.images))
""")
    assert unchanged
    # Replacing an active HDRI still retains the world from before activation.
    file_picker(qa,path)
    assert qa.eval(SETUP+'result=scene.mixar_zen_sky.previous_world.name if scene.mixar_zen_sky.previous_world else None') == original
    toggle(qa,False)
    assert qa.eval(SETUP+'result=scene.world.name if scene.world else None') == original
    assert qa.eval(SETUP+'result=[view.shading.use_scene_world, view.shading.use_scene_world_render]') == flags
    qa.click(area_type='TOPBAR',text='Edit');qa.click(popup=True,op='ED_OT_undo')
    qa.wait('drv.main_window().scene.world == drv.main_window().scene.mixar_zen_sky.sky_world',timeout=8)
    assert qa.eval(NODES+'result=uses_hdri(scene)')
    qa.click(area_type='TOPBAR',text='Edit');qa.click(popup=True,op='ED_OT_redo')
    qa.wait('drv.main_window().scene.world != drv.main_window().scene.mixar_zen_sky.sky_world',timeout=8)
    saved=qa.eval('result=bpy.context.preferences.view.ui_scale')
    try:
        for scale in (.8,1.0,1.5):
            qa.eval(f'bpy.context.preferences.view.ui_scale={scale}; result=True')
            qa.wait("bool(drv.find(op='MIXAR_OT_zen_load_hdri',region_type='HEADER'))",timeout=8)
            bounds=qa.eval(SETUP+'result=[area.x,area.x+area.width]')
            for widget in qa.find(**HEADER)['widgets']:
                if widget['type'] in {'Other','Label'}: continue
                assert bounds[0] <= widget['rect'][0] < widget['rect'][2] <= bounds[1],widget
            export=qa.find(**HEADER,text='Export')['widgets'][0]['rect']
            factor=qa.eval('result=bpy.context.preferences.system.ui_scale')
            assert (export[2]-export[0])/factor >= 80, export
            toggle(qa,True);toggle(qa,False)
            snap(qa,f'toolbar-{scale}')
    finally:
        qa.eval(f'bpy.context.preferences.view.ui_scale={saved}; result=True')
    qa.eval(SETUP+"scene.render.engine='BLENDER_WORKBENCH'; result=True")
    assert all(not w['enabled'] for op in ('MIXAR_OT_zen_set_sky','MIXAR_OT_zen_load_hdri') for w in qa.find(**HEADER,op=op)['widgets'])
    qa.eval(SETUP+"scene.render.engine='BLENDER_EEVEE'; result=True")
    project=OUT/'hdri-persistence.mixar'
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={str(project)!r}, check_existing=False))")
    qa.eval(f"result=str(bpy.ops.wm.open_mainfile(filepath={str(project)!r}))")
    qa.wait("bool(drv.find(op='MIXAR_OT_zen_load_hdri',region_type='HEADER'))",timeout=12)
    toggle(qa,True)
    assert qa.eval(NODES+'result=uses_hdri(scene)')
    toggle(qa,False)
    assert qa.eval(SETUP+'result=scene.world.name if scene.world else None') == original
    snap(qa,'final')
    return {'sky_properties':True,'hdri_import_and_rotation':True,'cancel_and_failure_safe':True,
            'restore_undo_and_reopen':True,'scales':[.8,1.0,1.5],'backend_calls':0}


if __name__=='__main__':
    run_scenario('zen_sky_controls_e2e',run)
