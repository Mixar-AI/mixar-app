#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit focused + / type / Enter replay. Uses a disposable mesh.

Run against an isolated QA instance with QA_HARNESS and MIXAR_QA_PORT set.
"""
import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


def run(qa):
    qa.wait("hasattr(bpy.types, 'MIXAR_MT_zen_modifier_catalog')", timeout=20)
    qa.press('ESC')
    qa.press('ESC')
    qa.eval("""
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.object.name = 'QA Modifier Search'
result = True
""")
    qa.click(area_type='VIEW_3D', region_type='TOOL_HEADER', text='Modifier')
    qa.click(popup=True, op='WM_OT_call_menu')
    qa.cmd('type', text='Bevel')
    qa.cmd('snap', path='/tmp/zen-modifier-search.png', area='VIEW_3D')
    qa.press('RET')
    qa.wait("drv.main_window().scene.objects['QA Modifier Search'].modifiers.active is not None", timeout=5)
    assert qa.eval("result=drv.main_window().scene.objects['QA Modifier Search'].modifiers.active.type") == 'BEVEL'
    return {'search_add': 'BEVEL', 'paid_requests': 0}


if __name__ == '__main__':
    run_scenario('zen_modifier_search_e2e', run)
