#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""No-credit texture popup replay in an isolated built Mixar instance.

QA_HARNESS=/path/to/mixar-qa-harness MIXAR_QA_PORT=4908 \
QA_SCENARIO_OUT=/tmp/zen-textures-e2e python3 tests/qa/zen_textures_e2e.py

Uses disposable scene/image fixtures. Feature actions use native UI events;
eval constructs fixtures and verifies the actual shader graph. Snapshots need
visual review, including the annotated popup and visible textured cube.
"""
import json
import os
from pathlib import Path
import struct
import sys
import zlib

sys.path.insert(0, str(Path(os.environ['QA_HARNESS']) / 'scenarios'))
from lib import run_scenario

OUT = Path(os.environ.get('QA_SCENARIO_OUT', '/tmp/zen-textures-e2e'))
STRIP = {'area_type': 'VIEW_3D', 'region_type': 'TOOL_HEADER'}
SETUP = """
from mixar.modules.workflow.core import zen_textures as textures
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
obj = w.scene.objects['QA Texture Cube']
mat = obj.active_material
shader = textures.surface_shader(mat, w.scene.render.engine)
"""


def png(path, colors):
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data))
    rows = b''.join(b'\0' + b''.join(bytes(colors[(x // 16 + y // 16) % len(colors)])
                    for x in range(128)) for y in range(128))
    path.write_bytes(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B', 128, 128, 8, 2, 0, 0, 0))
                    + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def open_card(qa):
    qa.press('ESC')
    qa.press('ESC')
    qa.click(**STRIP, text='Textures')
    qa.wait("bool(drv.find(popup=True,prop='active_material'))", timeout=5)


def channel_button(qa, channel, op):
    # Native buttons share an operator id. Resolve its channel from the visible
    # row label and use the button's OWN exported bounds, never guessed pixels.
    label = qa.find(popup=True, text=channel, but_type='Label')['widgets'][0]
    hits = qa.find(popup=True, op=op)['widgets']
    hits = [w for w in hits if abs(w['center'][1] - label['center'][1]) < 2]
    assert len(hits) == 1, (channel, op, hits)
    return hits[0]


def click_channel(qa, channel, op):
    button = channel_button(qa, channel, op)
    assert button['enabled'], (channel, op)
    qa.cmd('click_xy', window=button['window'], x=button['center'][0], y=button['center'][1])


def pick_file(qa, channel, path):
    open_card(qa)
    click_channel(qa, channel, 'MIXAR_OT_zen_load_texture')
    qa.wait("bool(drv.find(area_type='FILE_BROWSER',prop='filename'))", timeout=10)
    if path is None:
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_cancel')
    else:
        qa.eval(f"""
h = drv.find(area_type='FILE_BROWSER',prop='directory')[0]
params = h['_area'].spaces.active.params
params.directory = {str(path.parent).encode()!r}
params.filename = {path.name!r}
result = True
""")
        qa.click(area_type='FILE_BROWSER', prop='directory')
        window = qa.find(area_type='FILE_BROWSER', prop='directory')['widgets'][0]['window']
        qa.press('RET', window=window)
        qa.click(area_type='FILE_BROWSER', op='FILE_OT_execute')
    qa.wait("not any(a.type=='FILE_BROWSER' for w in bpy.context.window_manager.windows for a in w.screen.areas)", timeout=12)


def snap(qa, name, annotate=False):
    args = {'path': str(OUT / f'{name}.png'), 'area': 'VIEW_3D'}
    if annotate:
        args['annotate'] = {'op': 'MIXAR_OT_zen_load_texture'}
    qa.cmd('snap', **args)


def fixture(qa):
    OUT.mkdir(parents=True, exist_ok=True)
    png(OUT / 'base-color.png', [(210, 92, 30), (50, 90, 64)])
    png(OUT / 'normal.png', [(128, 128, 255), (155, 128, 252)])
    png(OUT / 'metallic.png', [(0, 0, 0), (90, 90, 90)])
    (OUT / 'broken.png').write_bytes(b'not an image')
    qa.wait("hasattr(bpy.types,'MIXAR_OT_zen_load_texture')", timeout=20)
    qa.press('ESC')
    qa.press('ESC')
    qa.eval("""
from mixar.modules.onboarding.core.tour import session
if session.current(): session.current().stop('qa')
w = drv.main_window()
a = next(a for a in w.screen.areas if a.type == 'VIEW_3D')
r = next(r for r in a.regions if r.type == 'WINDOW')
assert w.workspace.name == 'Zen Mode'
for old in list(bpy.data.objects):
    if old.name.startswith('QA Texture'): bpy.data.objects.remove(old, do_unlink=True)
w.scene = bpy.data.scenes.new('QA Textures')
w.scene.render.engine = 'BLENDER_EEVEE'
with bpy.context.temp_override(window=w, area=a, region=r):
    bpy.ops.mesh.primitive_cube_add()
    bpy.context.object.name = 'QA Texture Cube'
    bpy.ops.view3d.view_selected()
    a.spaces.active.region_3d.view_distance *= 1.6
    bpy.ops.ed.undo_push(message='Texture fixture')
a.spaces.active.shading.type = 'SOLID'
result = True
""")
    open_card(qa)
    assert qa.find(popup=True, text='Create Material')['total'] == 1
    snap(qa, 'empty')
    qa.click(popup=True, op='MIXAR_OT_zen_add_material', text='Create Material')
    qa.wait("drv.main_window().scene.objects['QA Texture Cube'].active_material is not None", timeout=5)
    open_card(qa)
    qa.click(popup=True, text='Show Material Preview')
    assert qa.eval(SETUP + "result=a.spaces.active.shading.type") == 'MATERIAL'
    # Loading itself should also turn on preview from solid shading.
    qa.eval(SETUP + "a.spaces.active.shading.type='SOLID'; result=True")
    pick_file(qa, 'Base Color', None)
    assert qa.eval(SETUP + "result=len(mat.node_tree.nodes)") == 2
    return {'create': True, 'preview_button': True, 'cancel_unchanged': True}


def load_channels(qa):
    for channel, filename in [('Base Color', 'base-color.png'), ('Roughness', 'base-color.png'),
                              ('Metallic', 'metallic.png'), ('Normal', 'normal.png')]:
        pick_file(qa, channel, OUT / filename)
        qa.wait(f"__import__('mixar.modules.workflow.core.zen_textures', fromlist=['surface_shader']).surface_shader(drv.main_window().scene.objects['QA Texture Cube'].active_material, 'BLENDER_EEVEE').inputs[{channel!r}].is_linked", timeout=5)
        state = qa.eval(SETUP + f"""
image, normal = textures.channel_nodes(shader.inputs[{channel!r}], {channel!r})
assert image and image.image
result = [image.image.colorspace_settings.name, bool(normal)]
""")
        assert state == [('sRGB' if channel == 'Base Color' else 'Non-Color'), channel == 'Normal'], state
    assert qa.eval(SETUP + "result=a.spaces.active.shading.type") == 'MATERIAL'
    assert qa.eval(SETUP + "result=len([n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeMapping'])") == 1
    open_card(qa)
    qa.cmd('set_text', widget={'popup': True, 'prop': 'default_value', 'text': 'U:', 'contains': True}, text='2')
    qa.cmd('set_text', widget={'popup': True, 'prop': 'default_value', 'text': 'V:', 'contains': True}, text='2')
    scale = qa.eval(SETUP + "result=list(textures.texture_mapping(shader).inputs['Scale'].default_value)")
    assert scale == [2, 2, 1], scale
    qa.cmd('set_text', widget={'popup': True, 'prop': 'default_value', 'text': 'Strength of the normal mapping effect'}, text='0.35')
    strength = qa.eval(SETUP + "result=textures.channel_nodes(shader.inputs['Normal'],'Normal')[1].inputs['Strength'].default_value")
    assert abs(strength - .35) < 1e-5
    snap(qa, 'all-maps', annotate=True)
    return {'channels': 4, 'color_spaces': True, 'shared_tiling': scale, 'normal_strength': strength}


def replace_remove_undo(qa):
    pick_file(qa, 'Base Color', OUT / 'metallic.png')
    assert qa.eval(SETUP + "result=len([n for n in mat.node_tree.nodes if n.bl_idname=='ShaderNodeTexImage'])") == 4
    pick_file(qa, 'Base Color', OUT / 'base-color.png')
    open_card(qa)
    click_channel(qa, 'Normal', 'MIXAR_OT_zen_remove_texture')
    assert qa.eval(SETUP + "result=shader.inputs['Normal'].is_linked") is False
    qa.press('ESC')
    qa.press('Z', ctrl=True)
    qa.wait("(lambda o: any(n.bl_idname=='ShaderNodeNormalMap' for n in o.active_material.node_tree.nodes))(drv.main_window().scene.objects['QA Texture Cube'])", timeout=5)
    assert qa.eval(SETUP + "result=shader.inputs['Normal'].is_linked") is True
    open_card(qa)
    snap(qa, 'undo-restored')
    # An invalid file must leave all nodes and links unchanged.
    before = qa.eval(SETUP + "result=[len(mat.node_tree.nodes),len(mat.node_tree.links),len(bpy.data.images)]")
    pick_file(qa, 'Base Color', OUT / 'broken.png')
    after = qa.eval(SETUP + "result=[len(mat.node_tree.nodes),len(mat.node_tree.links),len(bpy.data.images)]")
    assert before == after, (before, after)
    snap(qa, 'invalid-file')
    qa.press('ESC')
    return {'replace': True, 'remove': True, 'undo': True, 'invalid_file_unchanged': True}


def graph_and_sharing(qa):
    qa.press('ESC')
    qa.eval(SETUP + """
other = obj.copy()
other.data = obj.data.copy()
other.name = 'QA Texture Shared'
w.scene.collection.objects.link(other)
other.hide_set(True)
result = True
""")
    open_card(qa)
    snap(qa, 'shared-material')
    qa.click(popup=True, op='MIXAR_OT_zen_copy_material')
    assert qa.eval(SETUP + "result=mat != w.scene.objects['QA Texture Shared'].active_material")
    qa.eval(SETUP + """
noise = mat.node_tree.nodes.new('ShaderNodeTexNoise')
mat.node_tree.links.new(noise.outputs['Fac'], shader.inputs['Roughness'])
result = True
""")
    open_card(qa)
    assert qa.find(popup=True, text='Driven by nodes')['total'] == 1
    assert qa.find(popup=True, op='MIXAR_OT_zen_load_texture')['total'] == 3
    snap(qa, 'procedural-preserved')
    result = qa.eval(SETUP + f"""
count = len(mat.node_tree.nodes)
try:
    textures.load_texture(obj, mat, w.scene.render.engine, 'Roughness', {str(OUT / 'base-color.png')!r})
    raise AssertionError('Procedural input was overwritten')
except ValueError:
    pass
assert len(mat.node_tree.nodes) == count
# Preserve a shared image source and another shader consumer on replacement.
image, _ = textures.channel_nodes(shader.inputs['Base Color'], 'Base Color')
mat.node_tree.links.new(image.outputs['Color'], shader.inputs['Emission Color'])
name = image.name
textures.load_texture(obj, mat, w.scene.render.engine, 'Base Color', {str(OUT / 'base-color.png')!r})
assert textures.source_node(shader.inputs['Emission Color']).name == name
# Stale popover target cancels before it touches a different material.
with bpy.context.temp_override(window=w, area=a, region=r):
    try:
        bpy.ops.mixar.zen_load_texture(object_name=obj.name, material_name='Wrong material',
            channel='Base Color', filepath={str(OUT / 'base-color.png')!r})
        raise AssertionError('Stale target was accepted')
    except RuntimeError as exc:
        assert 'changed' in str(exc)
result = True
""")
    assert result
    return {'unique_material': True, 'procedural_preserved': True, 'shared_source_preserved': True, 'stale_target_rejected': True}


def no_uv_and_persistence(qa):
    qa.press('ESC')
    qa.eval(SETUP + """
obj.active_material = bpy.data.materials.new('QA Box Surface')
while obj.data.uv_layers: obj.data.uv_layers.remove(obj.data.uv_layers[0])
result = True
""")
    open_card(qa)
    assert not channel_button(qa, 'Normal', 'MIXAR_OT_zen_load_texture')['enabled']
    pick_file(qa, 'Base Color', OUT / 'base-color.png')
    state = qa.eval(SETUP + """
image, _ = textures.channel_nodes(shader.inputs['Base Color'], 'Base Color')
mapping = textures.texture_mapping(shader)
result = [image.projection, mapping.inputs['Vector'].links[0].from_socket.name]
""")
    assert state == ['BOX', 'Generated'], state
    open_card(qa)
    snap(qa, 'no-uv-box')
    qa.press('ESC')
    project = OUT / 'texture-project.blend'
    qa.eval(f"result=str(bpy.ops.wm.save_as_mainfile(filepath={str(project)!r},check_existing=False))")
    qa.eval(f"result=str(bpy.ops.wm.open_mainfile(filepath={str(project)!r}))")
    qa.wait("drv.main_window().scene.objects.get('QA Texture Cube') is not None", timeout=10)
    assert qa.eval(SETUP + "result=textures.channel_nodes(shader.inputs['Base Color'],'Base Color')[0].projection") == 'BOX'
    open_card(qa)
    snap(qa, 'saved-reopened', annotate=True)
    return {'box_without_uv': True, 'normal_requires_uv': True, 'save_reopen': True}


def run(qa):
    checks = {}
    for fn in (fixture, load_channels, replace_remove_undo, graph_and_sharing, no_uv_and_persistence):
        checks[fn.__name__] = qa.step(fn.__name__, fn, qa)
    verdict = {'checks': checks, 'paid_requests': 0, 'artifacts': str(OUT)}
    (OUT / 'verdict.json').write_text(json.dumps(verdict, indent=2) + '\n')
    return verdict


if __name__ == '__main__':
    run_scenario('zen_textures_e2e', run)
