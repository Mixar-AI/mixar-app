# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Resolve UV-only color graphs into glTF images in a disposable worker.

Cycles evaluates the graph, including color space conversion and procedural
nodes. A full UV square avoids overlapping/repeated UV islands on furniture.
Geometry-dependent graphs cannot use this shortcut.
"""

import bpy

from mixar.modules.common.i18n import iface_

CHANNELS = ('Base Color', 'Roughness', 'Metallic')
DIRECT = {'TEX_IMAGE', 'UVMAP', 'MAPPING', 'REROUTE', 'NORMAL_MAP', 'RGB', 'VALUE'}
EVALUABLE = DIRECT | {'RGB', 'VALUE', 'MIX_RGB', 'MIX', 'MATH', 'VECT_MATH',
                      'MAP_RANGE', 'VALTORGB', 'SEPARATE_COLOR', 'COMBINE_COLOR',
                      'SEPXYZ', 'COMBXYZ', 'RGBTOBW', 'INVERT', 'GAMMA',
                      'HUE_SAT', 'BRIGHTCONTRAST', 'TEX_NOISE', 'TEX_VORONOI',
                      'TEX_WAVE', 'TEX_CHECKER', 'TEX_GRADIENT'}


def _dependencies(socket, seen=None):
    seen = set() if seen is None else seen
    for link in socket.links:
        node = link.from_node
        if node in seen:
            continue
        seen.add(node)
        for source in node.inputs:
            _dependencies(source, seen)
    return seen


def material_plan(material):
    """Return channels requiring evaluation, or no work for direct PBR maps."""
    if not material or not material.node_tree:
        return None
    from mixar.modules.space_mixie_chat.core.export_preflight import active_mixar_nodes

    if active_mixar_nodes(material):
        return None  # The existing paint preparation owns these.
    outputs = [n for n in material.node_tree.nodes
               if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    if len(outputs) != 1 or len(outputs[0].inputs['Surface'].links) != 1:
        return None
    shader = outputs[0].inputs['Surface'].links[0].from_node
    if shader.type != 'BSDF_PRINCIPLED':
        return None
    channels, channel_uvs = [], {}
    for name in CHANNELS:
        nodes = _dependencies(shader.inputs[name])
        if not any(node.type not in DIRECT for node in nodes):
            continue
        uv_names = set()
        # Never reinterpret object/generated coordinates as UV coordinates.
        for node in nodes:
            if node.type not in EVALUABLE:
                raise RuntimeError(iface_('{material}: {channel} uses geometry-dependent or unsupported shader nodes').format(
                    material=material.name, channel=name))
            if node.type in {'TEX_NOISE', 'TEX_VORONOI', 'TEX_WAVE',
                             'TEX_CHECKER', 'TEX_GRADIENT'} and not node.inputs['Vector'].is_linked:
                raise RuntimeError(iface_('{material}: connect explicit UV coordinates before publishing {channel}').format(
                    material=material.name, channel=name))
            if node.type == 'UVMAP':
                uv_names.add(node.uv_map)
            if node.type == 'TEX_IMAGE' and not node.inputs['Vector'].is_linked:
                uv_names.add('')
            if node.type == 'TEX_IMAGE' and (not node.image or node.image.source == 'TILED'):
                raise RuntimeError(iface_('{material}: publishing this shader requires a non-tiled image').format(
                    material=material.name))
        if len(uv_names) > 1:
            raise RuntimeError(iface_('{material}: publishing {channel} requires a single UV map').format(
                material=material.name, channel=name))
        channel_uvs[name] = next(iter(uv_names), '')
        channels.append(name)
    if not channels:
        return None
    return {'material': material.name, 'shader': shader.name,
            'channels': channels, 'uvs': channel_uvs}


def plans_for_meshes(meshes):
    materials = {m for obj in meshes for m in obj.data.materials if m}
    plans = [plan for material in sorted(materials, key=lambda m: m.name)
             if (plan := material_plan(material))]
    for plan in plans:
        for obj in meshes:
            if not any(m and m.name == plan['material'] for m in obj.data.materials):
                continue
            names = {uv.name for uv in obj.data.uv_layers}
            if not names or any(uv and uv not in names for uv in plan['uvs'].values()):
                raise RuntimeError(iface_('{material}: required UV map is missing on {object}').format(
                    material=plan['material'], object=obj.name))
    return plans


def _uv_bounds(meshes, material, name):
    import numpy as np

    low, high = np.zeros(2), np.ones(2)
    for obj in meshes:
        if material not in obj.data.materials[:]:
            continue
        layer = obj.data.uv_layers.get(name) if name else next(
            (uv for uv in obj.data.uv_layers if uv.active_render), None)
        if layer is None or not len(layer.data):
            raise RuntimeError(f'{material.name}: missing source UV map')
        values = np.empty(len(layer.data) * 2, dtype=np.float32)
        layer.data.foreach_get('uv', values)
        values = values.reshape(-1, 2)
        if not np.isfinite(values).all():
            raise RuntimeError(f'{material.name}: invalid UV coordinates')
        low = np.minimum(low, values.min(axis=0))
        high = np.maximum(high, values.max(axis=0))
    return low.tolist(), high.tolist()


def bake_shader_textures(meshes, plans, progress=lambda *_: None, resolution=1024):
    """Worker only: replace complex inputs on copied materials with UV images.

    The host scene is never passed to this function. No lighting is baked:
    emission bakes evaluate each input in linear space, independent of lights.
    """
    scene = bpy.data.scenes.new('_MixarShaderBake')
    scene.render.engine = 'CYCLES'
    scene.cycles.device = 'CPU'
    scene.cycles.samples = 1
    scene.render.threads_mode = 'FIXED'
    scene.render.threads = 2
    scene.render.bake.margin = 0
    scene.render.bake.use_clear = True
    mesh = bpy.data.meshes.new('_MixarShaderBake')
    mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
    uv = mesh.uv_layers.new(name='_MixarBakeTarget')
    for loop, coord in zip(uv.data, [(0, 0), (1, 0), (1, 1), (0, 1)]):
        loop.uv = coord
    source_uv = mesh.uv_layers.new(name='_MixarBakeSource')
    mesh.uv_layers.active_index = 0
    uv.active_render = True
    plane = bpy.data.objects.new('_MixarShaderBake', mesh)
    scene.collection.objects.link(plane)
    plane.select_set(True, view_layer=scene.view_layers[0])
    scene.view_layers[0].objects.active = plane
    window = bpy.context.window
    previous = window.scene if window else None
    try:
        if window:
            window.scene = scene
        for index, plan in enumerate(plans):
            progress(index, len(plans))
            original = bpy.data.materials[plan['material']]
            material = original.copy()
            material.name = original.name + '_WebTextures'
            tree = material.node_tree
            shader = tree.nodes[plan['shader']]
            output = next(n for n in tree.nodes if n.type == 'OUTPUT_MATERIAL' and n.is_active_output)
            emission = tree.nodes.new('ShaderNodeEmission')
            target = tree.nodes.new('ShaderNodeTexImage')
            mesh.materials.clear()
            mesh.materials.append(material)
            images = []
            for channel in plan['channels']:
                uv_name = plan['uvs'][channel]
                low, high = _uv_bounds(meshes, original, uv_name)
                source_uv.name = uv_name or '_MixarBakeSource'
                for loop, coord in zip(source_uv.data, [(low[0], low[1]), (high[0], low[1]),
                                                        (high[0], high[1]), (low[0], high[1])]):
                    loop.uv = coord
                implicit_uvs = [n for n in tree.nodes if n.type == 'UVMAP' and not n.uv_map]
                for node in implicit_uvs:
                    node.uv_map = source_uv.name
                implicit_images = [n for n in _dependencies(shader.inputs[channel])
                                   if n.type == 'TEX_IMAGE' and not n.inputs['Vector'].is_linked]
                implicit_coords = tree.nodes.new('ShaderNodeUVMap')
                implicit_coords.uv_map = source_uv.name
                for node in implicit_images:
                    tree.links.new(implicit_coords.outputs['UV'], node.inputs['Vector'])
                source = shader.inputs[channel].links[0].from_socket
                image = bpy.data.images.new(f'{original.name}_{channel}_Web',
                                            width=resolution, height=resolution)
                image.colorspace_settings.name = 'sRGB' if channel == 'Base Color' else 'Non-Color'
                target.image = image
                tree.nodes.active = target
                tree.links.new(source, emission.inputs['Color'])
                tree.links.new(emission.outputs[0], output.inputs['Surface'])
                with bpy.context.temp_override(scene=scene, view_layer=scene.view_layers[0],
                                               object=plane, active_object=plane,
                                               selected_objects=[plane], selected_editable_objects=[plane]):
                    status = bpy.ops.object.bake(type='EMIT')
                if 'FINISHED' not in status:
                    raise RuntimeError(f'{original.name}: shader texture bake failed')
                image.pack()
                for node in implicit_uvs:
                    node.uv_map = ''
                tree.nodes.remove(implicit_coords)
                images.append((channel, image, low, high))
            tree.links.new(shader.outputs[0], output.inputs['Surface'])
            tree.nodes.remove(emission)
            tree.nodes.remove(target)
            for channel, image, low, high in images:
                coords = tree.nodes.new('ShaderNodeUVMap')
                coords.uv_map = plan['uvs'][channel]
                texture = tree.nodes.new('ShaderNodeTexImage')
                texture.image = image
                texture.extension = 'EXTEND'
                mapping = tree.nodes.new('ShaderNodeMapping')
                for axis in range(2):
                    span = high[axis] - low[axis]
                    mapping.inputs['Scale'].default_value[axis] = 1 / span
                    mapping.inputs['Location'].default_value[axis] = -low[axis] / span
                tree.links.new(coords.outputs['UV'], mapping.inputs['Vector'])
                tree.links.new(mapping.outputs['Vector'], texture.inputs['Vector'])
                tree.links.new(texture.outputs['Color'], shader.inputs[channel])
            for obj in meshes:
                for slot in obj.material_slots:
                    if slot.material == original:
                        slot.material = material
        progress(len(plans), len(plans))
    finally:
        if window:
            window.scene = previous
        bpy.data.objects.remove(plane, do_unlink=True)
        bpy.data.meshes.remove(mesh)
        bpy.data.scenes.remove(scene)
