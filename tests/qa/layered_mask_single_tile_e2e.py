#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Real Cycles cavity+FXAA mask on repeating UVs, in an isolated QA app.

No backend turn or generation calls. Requires QA_HARNESS and MIXAR_QA_PORT.
Leaves a QA cube with a single 1K geometry mask; does not load the user scene.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    state = qa.step('repeating_uv_mask_bake', qa.eval, '''import os,time,numpy as np
from mixar.modules.paint.layered_build.mask_uv import mask_bake_uv
from mixar.modules.paint.ui.udim.udim_utils import get_tile_numbers
assert os.environ.get('MIXAR_QA')=='1'
win=drv.main_window()
area=next(a for a in win.screen.areas if a.type=='VIEW_3D')
region=next(r for r in area.regions if r.type=='WINDOW')
with bpy.context.temp_override(window=win,area=area,region=region):
 bpy.ops.mesh.primitive_cube_add()
 obj=bpy.context.object
 obj.name='QA_Repeating_UV_Mask'
 uv=obj.data.uv_layers.active
 original=np.empty(len(uv.data)*2,dtype=np.float32)
 uv.data.foreach_get('uv',original)
 original=original*100-20
 uv.data.foreach_set('uv',original)
 original_name=uv.name
 source_tiles=get_tile_numbers([obj],original_name)
 assert len(source_tiles)>4,len(source_tiles)
 bake_uv=mask_bake_uv(obj,original_name)
 assert get_tile_numbers([obj],bake_uv)==[1001]
 after=np.empty(len(uv.data)*2,dtype=np.float32)
 uv.data.foreach_get('uv',after)
 np.testing.assert_array_equal(original,after)
 assert obj.data.uv_layers.active.name==original_name
 assert mask_bake_uv(obj,original_name)==bake_uv
 bpy.ops.layers.create_material('EXEC_DEFAULT')
 mask_name='QA Single Tile Cavity '+__import__('uuid').uuid4().hex[:6]
 started=time.monotonic()
 status=bpy.ops.wm.m_bake_to_layer('EXEC_DEFAULT',name=mask_name,target_type='MASK',type='CAVITY',uv_map=bake_uv,use_udim=False,width=1024,height=1024,samples=1,hdr=False,fxaa=True,bake_device='CPU')
 elapsed=time.monotonic()-started
 assert 'FINISHED' in status,str(status)
 images=[im for im in bpy.data.images if im.name==mask_name]
 assert len(images)==1,[im.name for im in images]
 image=images[0]
 assert image.source!='TILED' and list(image.size)==[1024,1024],(image.source,list(image.size))
 result={'source_tiles':len(source_tiles),'mask_tiles':1,'size':list(image.size),'seconds':round(elapsed,3),'original_uv_preserved':True,'image':image.name}
''')
    out = Path(os.environ.get('QA_SCENARIO_OUT', '/private/tmp/uat6-mask-freeze-evidence'))
    out.mkdir(parents=True, exist_ok=True)
    qa.snap(str(out / 'after-mask-bake.png'))
    return {'state': state, 'snaps': [str(out / 'after-mask-bake.png')]}


if __name__ == '__main__':
    run_scenario('layered_mask_single_tile_e2e', run)
