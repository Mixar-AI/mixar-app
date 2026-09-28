# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Output-aware texture edits. Only explicit operators mutate the graph."""
import bpy
from ..constants import ZEN_TEXTURE_CHANNELS, ZEN_TEXTURE_ROLE


def source_node(socket):
    """Follow reroutes, never an unrelated shader or a cyclic path."""
    visited = set()
    while socket and socket.is_linked:
        node = socket.links[0].from_node
        if node.as_pointer() in visited:
            return None
        visited.add(node.as_pointer())
        if node.bl_idname != 'NodeReroute':
            return node
        socket = node.inputs[0]
    return None


def surface_shader(material, engine):
    tree = material.node_tree if material else None
    if tree is None:
        return None
    target = 'CYCLES' if engine == 'CYCLES' else 'EEVEE'
    output = tree.get_output_node(target) or tree.get_output_node('ALL')
    shader = source_node(output.inputs.get('Surface')) if output else None
    return shader if shader and shader.bl_idname == 'ShaderNodeBsdfPrincipled' else None


def channel_nodes(socket, channel):
    """Return (image, normal converter); unfamiliar connections are read-only."""
    source = source_node(socket)
    normal = None
    if channel == 'Normal':
        if not source or source.bl_idname != 'ShaderNodeNormalMap':
            return None, None
        normal = source
        source = source_node(normal.inputs.get('Color'))
    image = source if source and source.bl_idname == 'ShaderNodeTexImage' else None
    return image, normal


def editable_channel(obj, material, engine, channel, *, loading=True):
    if channel not in {item[0] for item in ZEN_TEXTURE_CHANNELS}:
        raise ValueError('Choose a supported texture channel')
    if (not material or not material.is_editable or not material.node_tree
            or not material.node_tree.is_editable):
        raise ValueError('Make the material local before editing its textures')
    shader = surface_shader(material, engine)
    if shader is None:
        raise ValueError('Edit this shader in Engine Mode')
    socket = shader.inputs[channel]
    image, normal = channel_nodes(socket, channel)
    if socket.is_linked and image is None:
        raise ValueError('This channel is driven by nodes; edit it in Engine Mode')
    if loading and channel == 'Normal' and not obj.data.uv_layers:
        raise ValueError('Add a UV map in Engine Mode before loading a normal map')
    return shader, socket, image, normal


def _new_node(tree, kind, role, created):
    node = tree.nodes.new(kind)
    node[ZEN_TEXTURE_ROLE] = role
    created.append(node)
    return node


def texture_mappings(shader):
    """Only expose mapping nodes that drive active channels."""
    mappings = []
    for channel, _, _ in ZEN_TEXTURE_CHANNELS:
        image, _ = channel_nodes(shader.inputs.get(channel), channel)
        node = source_node(image.inputs['Vector']) if image else None
        if node and node.get(ZEN_TEXTURE_ROLE) == 'MAPPING' and node not in mappings:
            mappings.append(node)
    return mappings


def mapping_uses_uv(mapping):
    socket = mapping.inputs['Vector']
    return socket.is_linked and socket.links[0].from_socket.name == 'UV'


def texture_mapping(shader):
    return next(iter(texture_mappings(shader)), None)


def _mapping(tree, shader, obj, created):
    # UVs can be added after the first box map. A normal map must never inherit
    # Generated coordinates just because another channel was loaded earlier.
    mapping = next((node for node in texture_mappings(shader)
                    if mapping_uses_uv(node) == bool(obj.data.uv_layers)), None)
    if mapping:
        return mapping
    coords = _new_node(tree, 'ShaderNodeTexCoord', 'COORDINATES', created)
    mapping = _new_node(tree, 'ShaderNodeMapping', 'MAPPING', created)
    mapping.label = 'Texture Tiling'
    coords.location = (shader.location.x - 1000, shader.location.y)
    mapping.location = (shader.location.x - 800, shader.location.y)
    tree.links.new(coords.outputs['UV' if obj.data.uv_layers else 'Generated'],
                   mapping.inputs['Vector'])
    return mapping


def _remove_unused_nodes(tree, node):
    # Prune only this obsolete branch, never other disconnected/user nodes.
    pending = {node.as_pointer(): node} if node else {}
    while pending:
        _, current = pending.popitem()
        if (not current.get(ZEN_TEXTURE_ROLE)
                or any(s.is_linked for s in current.outputs)):
            continue
        for socket in current.inputs:
            for link in socket.links:
                source = link.from_node
                pending[source.as_pointer()] = source
        image = current.image if current.bl_idname == 'ShaderNodeTexImage' else None
        tree.nodes.remove(current)
        if image and image.get(ZEN_TEXTURE_ROLE) and image.users == 0:
            bpy.data.images.remove(image)


def load_texture(obj, material, engine, channel, filepath):
    shader, socket, old_image, old_normal = editable_channel(obj, material, engine, channel)
    if not filepath:
        raise ValueError('Choose an image file')
    # Reusing a color image as data must not change its other material uses.
    image = bpy.data.images.load(bpy.path.abspath(filepath), check_existing=False)
    created = []
    tree = material.node_tree
    try:
        # Image loading is lazy; reading size actually decodes the buffer.
        if not all(image.size):
            raise ValueError('The selected file does not contain a readable image')
        image[ZEN_TEXTURE_ROLE] = 'IMAGE'
        if channel != 'Base Color':
            image.colorspace_settings.name = 'Non-Color'
        texture = _new_node(tree, 'ShaderNodeTexImage', 'IMAGE', created)
        texture.label = channel
        texture.image = image
        index = next(i for i, item in enumerate(ZEN_TEXTURE_CHANNELS) if item[0] == channel)
        texture.location = (shader.location.x - 500, shader.location.y - index * 280)
        if old_image:
            texture.projection = old_image.projection
            texture.projection_blend = old_image.projection_blend
            texture.extension = old_image.extension
            texture.interpolation = old_image.interpolation
            if old_image.inputs['Vector'].is_linked:
                tree.links.new(old_image.inputs['Vector'].links[0].from_socket,
                               texture.inputs['Vector'])
        else:
            mapping = _mapping(tree, shader, obj, created)
            tree.links.new(mapping.outputs['Vector'], texture.inputs['Vector'])
            if not obj.data.uv_layers:
                texture.projection = 'BOX'
                texture.projection_blend = 0.2
        result = texture.outputs['Color']
        if channel == 'Normal':
            normal = _new_node(tree, 'ShaderNodeNormalMap', 'NORMAL', created)
            normal.location = (shader.location.x - 220, texture.location.y)
            if old_normal:
                normal.space = old_normal.space
                normal.uv_map = old_normal.uv_map
                strength = old_normal.inputs['Strength']
                normal.inputs['Strength'].default_value = strength.default_value
                if strength.is_linked:
                    tree.links.new(strength.links[0].from_socket, normal.inputs['Strength'])
            tree.links.new(result, normal.inputs['Color'])
            result = normal.outputs['Normal']
        # Commit last: failed decode/setup leaves the original connection intact.
        tree.links.new(result, socket)
    except Exception:
        for node in reversed(created):
            tree.nodes.remove(node)
        bpy.data.images.remove(image)
        raise
    _remove_unused_nodes(tree, old_normal or old_image)
    return image


def remove_texture(obj, material, engine, channel):
    _, socket, image, normal = editable_channel(obj, material, engine, channel, loading=False)
    if image is None:
        raise ValueError('There is no image texture in this channel')
    tree = material.node_tree
    for link in list(socket.links):
        tree.links.remove(link)
    _remove_unused_nodes(tree, normal or image)
