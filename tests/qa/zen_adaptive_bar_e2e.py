#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Focused no-credit native drag/close/restore and add/apply replay.

Run against an isolated app using QA_HARNESS and MIXAR_QA_PORT.
"""
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

STRIP = {'area_type': 'VIEW_3D', 'region_type': 'TOOL_HEADER'}


def run(qa):
    qa.wait("hasattr(bpy.types, 'MIXAR_MT_zen_modifier_catalog')", timeout=30)
    qa.press('ESC')
    qa.press('ESC')
    qa.eval("""
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mesh.primitive_cube_add()
result = True
""")
    grip = qa.find(**STRIP, op='VIEW2D_OT_pan')['widgets'][0]
    x, y = grip['center']
    qa.cmd('drag', **{'from': {**STRIP, 'op': 'VIEW2D_OT_pan'},
                     'to': {'x': x - 100, 'y': y - 100}, 'steps': 12})
    moved = qa.find(**STRIP, op='VIEW2D_OT_pan')['widgets'][0]['center']
    assert abs(moved[0] - x + 100) < 5 and abs(moved[1] - y + 100) < 5
    qa.cmd('snap', path='/tmp/zen-adaptive-drag.png', area='VIEW_3D')
    qa.click(**STRIP, text='Modifier')
    qa.click(popup=True, op='WM_OT_call_menu')
    qa.click(popup=True, op='OBJECT_OT_modifier_add', text='Bevel')
    qa.wait("bool(drv.find(popup=True, op='OBJECT_OT_modifier_apply'))", timeout=5)
    assert qa.eval("result=drv.main_window().view_layer.objects.active.modifiers.active.type") == 'BEVEL'
    qa.click(popup=True, op='OBJECT_OT_modifier_apply')
    qa.wait("bool(drv.find(popup=True, text='Add a modifier with +.'))", timeout=5)
    assert qa.eval("result=len(drv.main_window().view_layer.objects.active.modifiers)") == 0
    qa.press('ESC')
    qa.press('ESC')
    qa.click(**STRIP, op='WM_OT_context_toggle')
    qa.wait("bool(drv.find(area_type='VIEW_3D', text='Object Controls'))", timeout=5)
    qa.click(area_type='VIEW_3D', text='Object Controls')
    qa.wait("bool(drv.find(op='VIEW2D_OT_pan'))", timeout=5)
    return {'two_axis_drag': True, 'native_add_apply_refresh': True,
            'close_restore': True, 'paid_requests': 0}


if __name__ == '__main__':
    run_scenario('zen_adaptive_bar_e2e', run)
