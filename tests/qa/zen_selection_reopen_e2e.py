# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Focused close/reselect regression; run against an isolated QA app."""
import os
import sys
import time
sys.path.insert(0, os.path.join(os.environ['QA_HARNESS'], 'scenarios'))
from lib import QA
q=QA(int(os.environ.get('MIXAR_QA_PORT', '4899')))
q.press('ESC');q.press('ESC')
setup="w=drv.main_window(); a=next(a for a in w.screen.areas if a.type=='VIEW_3D'); r=next(r for r in a.regions if r.type=='WINDOW'); "
def op(code):
    return q.eval(setup+"exec("+repr("with bpy.context.temp_override(window=w,area=a,region=r):\n "+code.replace('\n','\n '))+"); result=True")
def close():
    time.sleep(0.3)  # Let selection notifications and layout reach the next frame.
    q.wait("next(r for a in drv.main_window().screen.areas if a.type=='VIEW_3D' for r in a.regions if r.type=='TOOL_HEADER').height > 1", timeout=5)
    q.click(area_type='VIEW_3D',region_type='TOOL_HEADER',op='MIXAR_OT_zen_object_controls_show')
    q.wait("not next(a for a in drv.main_window().screen.areas if a.type=='VIEW_3D').spaces.active.show_region_tool_header",timeout=5)
op('bpy.ops.mesh.primitive_cube_add()\nbpy.context.object.name="QA Reopen Mesh"')
q.wait("bool(drv.find(area_type='VIEW_3D',region_type='TOOL_HEADER',text='Modifier'))",timeout=5)
close()
op('bpy.ops.object.light_add(type="POINT")')
q.wait("bool(drv.find(area_type='VIEW_3D',region_type='TOOL_HEADER',prop='energy'))",timeout=5)
print('New light restores bar',flush=True)
close()
op('bpy.ops.object.select_all(action="DESELECT")')
op('bpy.ops.object.select_all(action="SELECT")')
q.wait("bool(drv.find(area_type='VIEW_3D',region_type='TOOL_HEADER',prop='energy'))",timeout=5)
print('Deselect/reselect restores bar',flush=True)
close()
q.eval('drv.main_window().view_layer.objects.active=bpy.data.objects["QA Reopen Mesh"]; result=True')
q.wait("bool(drv.find(area_type='VIEW_3D',region_type='TOOL_HEADER',text='Modifier'))",timeout=5)
print('Existing mesh selection restores bar',flush=True)
q.cmd('snap',path='/private/tmp/mixar-selection-reopened.png',area='VIEW_3D')
