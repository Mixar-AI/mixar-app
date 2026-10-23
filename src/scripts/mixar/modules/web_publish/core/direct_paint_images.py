# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Direct image export of an unmodified, single UV-mapped PBR fill.

Stage its existing channel images for the shared export material builder.
These are export-only bindings, not permanent bake caches. Anything requiring
compositing, masks, transforms or procedural evaluation stays on the bake path.
"""

from contextlib import contextmanager
import math


def _unit(value):
    return isinstance(value, (int, float)) and math.isclose(value, 1, abs_tol=1e-7)


def direct_images(obj, node):
    mp = node.node_tree.mp
    if mp.use_baked:
        return None
    layers = [layer for layer in getattr(mp, 'layers', ()) if layer.enable]
    if len(layers) != 1:
        return None
    layer = layers[0]
    if (layer.type != 'COLOR' or layer.parent_idx != -1 or layer.texcoord_type != 'UV'
            or len(layer.masks) or len(layer.modifiers)):
        return None
    if any(not math.isclose(a, b, abs_tol=1e-7)
           for prop, expected in [('translation', (0, 0, 0)), ('rotation', (0, 0, 0)), ('scale', (1, 1, 1))]
           for a, b in zip(getattr(layer, prop), expected)):
        return None
    from mixar.modules.paint.core.layer.check_layers import is_any_layer_using_channel
    from mixar.modules.paint.core.node.get_nodes import get_channel_source, get_channel_source_1
    from mixar.modules.paint.core.io.utils.bsdf_connections import get_bsdf_socket_name
    from mixar.modules.paint.utils.common_entity import get_entity_prop_value

    if not _unit(get_entity_prop_value(layer, 'intensity_value')):
        return None
    if (getattr(layer, 'enable_uniform_scale', False)
            and not _unit(get_entity_prop_value(layer, 'uniform_scale_value'))):
        return None
    if layer.blend_linked and layer.linked_blend_type != 'MIX':
        return None
    render_uv = next((uv.name for uv in obj.data.uv_layers if uv.active_render), None)
    if not render_uv or layer.uv_name != render_uv:
        return None
    if any(socket.is_linked for socket in node.inputs):
        return None

    images = []
    shader = None
    for index, root in enumerate(mp.channels):
        if not is_any_layer_using_channel(root, node):
            continue
        channel = layer.channels[index]
        if (not channel.enable or len(channel.modifiers) or len(root.modifiers)
                or channel.blend_type != 'MIX' or root.enable_alpha
                or not _unit(get_entity_prop_value(channel, 'intensity_value'))
                or root.name not in {'Color', 'Base Color', 'Metallic', 'Roughness', 'Normal'}):
            return None
        if root.type == 'NORMAL':
            if (channel.normal_map_type != 'NORMAL_MAP' or not channel.override_1
                    or channel.override_1_type != 'IMAGE'
                    or not _unit(get_entity_prop_value(channel, 'normal_strength'))):
                return None
            source = get_channel_source_1(channel, layer)
        else:
            if not channel.override or channel.override_type != 'IMAGE':
                return None
            source = get_channel_source(channel, layer)
        if (source is None or source.type != 'TEX_IMAGE' or not source.image
                or source.image.source == 'TILED' or source.interpolation not in {'Linear', 'Cubic'}):
            return None
        socket = node.outputs.get(root.name)
        target = get_bsdf_socket_name(root.name)
        if (not socket or not socket.links or not target
                or any(link.to_node.type != 'BSDF_PRINCIPLED' or link.to_socket.name != target
                       for link in socket.links)):
            return None
        for link in socket.links:
            if shader is not None and shader != link.to_node:
                return None
            shader = link.to_node
        images.append((root, source.image))
    if shader is None:
        return None
    outputs = [n for n in node.id_data.nodes
               if n.type == 'OUTPUT_MATERIAL' and n.is_active_output]
    if (len(outputs) != 1 or len(outputs[0].inputs['Surface'].links) != 1
            or outputs[0].inputs['Surface'].links[0].from_node != shader):
        return None
    for name in ['Alpha', 'IOR', 'Specular IOR Level', 'Transmission Weight', 'Coat Weight', 'Sheen Weight']:
        socket = shader.inputs.get(name)
        default = {'Alpha': 1, 'IOR': 1.5, 'Specular IOR Level': 0.5}.get(name, 0)
        if socket and (socket.is_linked or not math.isclose(socket.default_value, default, abs_tol=1e-7)):
            return None
    emission = shader.inputs.get('Emission Color')
    strength = shader.inputs.get('Emission Strength')
    if strength and strength.is_linked:
        return None
    if (emission and (strength is None or strength.default_value != 0)
            and (emission.is_linked or any(value != 0 for value in emission.default_value[:3]))):
        return None
    return images or None


@contextmanager
def staged_direct_paint_images(meshes):
    from mixar.modules.space_mixie_chat.core.export_preflight import active_mixar_nodes

    staged = []
    plans = {}
    # A shared stack must be eligible for every exported user of that stack;
    # otherwise a different render UV on a second object would sample it wrong.
    for obj in meshes:
        for material in obj.data.materials:
            nodes = active_mixar_nodes(material)
            if len(nodes) != 1:
                continue
            node = nodes[0]
            tree = node.node_tree
            marker = tree.as_pointer()
            images = direct_images(obj, node)
            if marker not in plans:
                plans[marker] = [tree, images]
            elif images is None:
                plans[marker][1] = None
    try:
        for tree, images in plans.values():
            if images is None:
                continue
            mp = tree.mp
            state = (tree, mp.use_baked, mp.halt_update, tree.nodes.active, [], [])
            staged.append(state)
            mp.halt_update = True
            for channel, image in images:
                state[4].append((channel, channel.baked))
                texture = tree.nodes.new('ShaderNodeTexImage')
                state[5].append(texture)
                texture.image = image
                channel.baked = texture.name
            # Leave the source graph alone. The export material builder
            # reads these image bindings; no display callback is needed.
            mp.use_baked = True
            mp.halt_update = state[2]
        yield
    finally:
        for tree, use_baked, halt_update, active, bindings, textures in reversed(staged):
            tree.mp.halt_update = True
            try:
                for channel, name in bindings:
                    channel.baked = name
                tree.mp.use_baked = use_baked
                for texture in textures:
                    tree.nodes.remove(texture)
                tree.nodes.active = active
            finally:
                tree.mp.halt_update = halt_update
