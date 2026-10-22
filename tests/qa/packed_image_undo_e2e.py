#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit packed texture undo/redo, cache preservation and save/reopen.

Run with QA_HARNESS and QA_SCENARIO_OUT against an isolated event-simulate
app. Requires the harness's dismiss_chat command. Exercises both native undo
modes and the actual keyboard bindings, with no LLM or provider dependency.
"""
import json
import os
from pathlib import Path
import sys

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario


SETUP = '''
w = drv.main_window()
s = w.scene
o = next(o for o in s.objects if o.type == 'MESH')
o.name = 'QA_TEXTURE_CUBE'
o.data.materials.clear()
m = bpy.data.materials.new('QA_TEXTURE_MATERIAL')
m.use_nodes = True
o.data.materials.append(m)
def image(name, color):
    im = bpy.data.images.new(name, width=64, height=64, alpha=True)
    pixels = []
    for y in range(64):
        for x in range(64):
            pixels.extend(color if (x//8 + y//8) % 2 == 0 else (1,1,0,1))
    im.pixels.foreach_set(pixels)
    im.update()
    im.pack()
    return im
im = image('QA_PACKED', (0,0,1,1))
n = m.node_tree.nodes.new('ShaderNodeTexImage')
n.image = im
m.node_tree.links.new(n.outputs['Color'], m.node_tree.nodes['Principled BSDF'].inputs['Base Color'])
# An unchanged packed source with unsaved pixels must KEEP its live cache,
# even when its ID is re-read for a metadata edit.
sentinel = image('QA_DIRTY', (0,0,1,1))
m.node_tree.nodes.new('ShaderNodeTexImage').image = sentinel
sentinel.pixels.foreach_set([1,0,1,1] * 4096)
sentinel.update()
assert bpy.context.window_manager.mixar_undo_push('QA texture baseline', scene=s)
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
a.spaces.active.shading.type = 'MATERIAL'
r = next(r for r in a.regions if r.type == 'WINDOW')
for other in s.objects:
    other.select_set(other == o)
w.view_layer.objects.active = o
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.view3d.view_selected()
result = True
'''

EDIT = '''
im = bpy.data.images['QA_PACKED']
pixels = list(im.pixels)
for i in range(0, len(pixels), 4):
    if pixels[i+2] > .5:
        pixels[i:i+4] = [0,1,0,1]
im.pixels.foreach_set(pixels)
im.update()
im.pack()
bpy.data.images['QA_DIRTY'].name = 'QA_DIRTY_RENAMED'
assert bpy.context.window_manager.mixar_undo_push('QA texture edit', scene=drv.main_window().scene)
result = True
'''

SNAPSHOT = '''
import array, hashlib
def digest(im):
    pixels = array.array('f', im.pixels[:])
    return {'pixels': hashlib.sha256(pixels.tobytes()).hexdigest(),
            'packed': hashlib.sha256(bytes(im.packed_file.data)).hexdigest(),
            'first': list(pixels[:4]), 'name': im.name}
im = bpy.data.images['QA_PACKED']
sentinel = next(i for i in bpy.data.images if i.name.startswith('QA_DIRTY'))
result = {'texture': digest(im), 'sentinel': digest(sentinel)}
'''


def focus(qa):
    return qa.eval('''
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
drv.move_to(w, r.x + r.width // 2, r.y + r.height // 2)
result = {'window': w.as_pointer(), 'keys': {}}
for op in ('ed.undo', 'ed.redo'):
    k = next(k for k in bpy.context.window_manager.keyconfigs.active.keymaps['Screen'].keymap_items
             if k.active and k.idname == op and k.type == 'Z' and k.value == 'PRESS')
    result['keys'][op] = {n: bool(getattr(k,n)) for n in ('ctrl','alt','shift','oskey')}
''')


def run_mode(qa, out, per_tab, edit=None):
    qa.cmd('reset_state')
    qa.cmd('wait_login', timeout=60)
    qa.eval(f'bpy.context.window_manager.mixar_per_tab_undo = {per_tab!r}\nresult=True')
    qa.eval(SETUP)
    qa.cmd('dismiss_chat')
    states = {}

    def capture(name):
        state = qa.eval(SNAPSHOT)
        states[name] = state
        (out / 'states.json').write_text(json.dumps(states, indent=2))
        qa.snap(str(out / f'{name}.png'))
        return state

    before = capture('before')
    if edit is None:
        qa.eval(EDIT)
    else:
        edit(qa)
    qa.cmd('dismiss_chat')
    edited = capture('edited')
    assert edited['texture']['first'] == [0,1,0,1], edited
    assert edited['texture']['packed'] != before['texture']['packed'], edited
    for operation, expected, name in (
        ('ed.undo', before, 'undone'), ('ed.redo', edited, 'redone'),
        ('ed.undo', before, 'undone_again'),
    ):
        keys = focus(qa)
        qa.press('Z', window=keys['window'], **keys['keys'][operation])
        expected_name = expected['sentinel']['name']
        qa.wait(f'{expected_name!r} in bpy.data.images', timeout=5)
        actual = capture(name)
        assert actual == expected, (operation, actual, expected)
        assert actual['sentinel']['first'] == [1,0,1,1], actual
    path = str(out / 'undone.mixar')
    qa.eval(f"assert bpy.ops.wm.save_as_mainfile(filepath={path!r}, check_existing=False, thumbnail=False) == {{'FINISHED'}}\nresult=True")
    qa.eval(f"assert bpy.ops.wm.open_mainfile(filepath={path!r}) == {{'FINISHED'}}\nresult=True")
    qa.wait("'QA_PACKED' in bpy.data.images", timeout=20)
    qa.cmd('dismiss_chat')
    reopened = capture('reopened')
    assert reopened['texture'] == before['texture'], reopened
    return {'per_tab': per_tab, 'states': states}


def run(qa):
    root = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/qa-packed-image-undo'))
    original = qa.eval('result=bpy.context.window_manager.mixar_per_tab_undo')
    rows = []
    try:
        for per_tab in (True, False):
            out = root / ('per-tab' if per_tab else 'document')
            out.mkdir(parents=True, exist_ok=True)
            rows.append(qa.step('packed_image_undo', run_mode, qa, out, per_tab))
    finally:
        qa.eval(f'bpy.context.window_manager.mixar_per_tab_undo = {original!r}\nresult=True')
    return {'modes': rows, 'backend_turns': 0}


if __name__ == '__main__':
    run_scenario('packed_image_undo_e2e', run)
