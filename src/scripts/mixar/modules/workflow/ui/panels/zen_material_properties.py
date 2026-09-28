# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Compact surface values, image channels and the mapping that drives them."""
from ...constants import ZEN_TEXTURE_CHANNELS
from ...core.zen_textures import surface_shader, channel_nodes, texture_mappings, mapping_uses_uv


def texture_action(layout, operator, obj, material, channel=None, **kwargs):
    op = layout.operator(operator, **kwargs)
    op.object_name = obj.name
    op.material_name = material.name
    if channel:
        op.channel = channel
    return op


def draw_material_properties(layout, context, material):
    obj = context.object
    if material.users > 1:
        shared = layout.row()
        shared.label(text=f'Shared material · {material.users} users', icon='LINKED')
        copy = shared.row()
        copy.enabled = obj.is_editable and obj.data.is_editable and obj.data.users == 1
        texture_action(copy, 'mixar.zen_copy_material', obj, material, text='Make Unique')
    shader = surface_shader(material, context.scene.render.engine)
    if shader is None:
        layout.label(text='Edit this shader in Engine Mode.', icon='NODETREE')
        return
    body = layout.column()
    body.use_property_split = False
    body.enabled = obj.is_editable and material.is_editable and material.node_tree.is_editable
    body.separator(factor=0.4)
    for channel, label, _ in ZEN_TEXTURE_CHANNELS:
        socket = shader.inputs.get(channel)
        if socket is None:
            continue
        image_node, normal = channel_nodes(socket, channel)
        row = body.row(align=True)
        name = row.row()
        name.ui_units_x = 5.2
        name.label(text=label)
        if socket.is_linked and image_node is None:
            row.label(text='Driven by nodes', icon='NODETREE')
            continue
        controls = row.row(align=True)
        if image_node:
            controls.label(text=image_node.image.name if image_node.image else 'Missing image',
                           icon='IMAGE_DATA')
        elif channel == 'Normal':
            controls.label(text='No map' if obj.data.uv_layers else 'UV map required')
        else:
            controls.prop(socket, 'default_value', text='', slider=True)
        load = row.row(align=True)
        load.enabled = channel != 'Normal' or bool(obj.data.uv_layers)
        # The popover region is gone when the file selector returns.
        load.operator_context = 'INVOKE_REGION_WIN'
        texture_action(load, 'mixar.zen_load_texture', obj, material, channel,
                       text='', icon='FILE_FOLDER')
        if image_node:
            texture_action(row, 'mixar.zen_remove_texture', obj, material, channel,
                           text='', icon='X')
        if normal:
            strength = body.row()
            strength.use_property_split = True
            if normal.inputs['Strength'].is_linked:
                strength.label(text='Normal strength driven by nodes', icon='NODETREE')
            else:
                strength.prop(normal.inputs['Strength'], 'default_value', text='Strength')
    mappings = texture_mappings(shader)
    for mapping in mappings:
        body.separator(factor=0.5)
        uv = mapping_uses_uv(mapping)
        row = body.row()
        row.label(text='Tiling', icon='UV')
        row.label(text='UV mapping' if uv else 'Box mapping')
        if mapping.inputs['Scale'].is_linked:
            body.label(text='Tiling driven by nodes', icon='NODETREE')
        else:
            scale = body.row(align=True)
            for i, label in enumerate(('U', 'V') if uv else ('X', 'Y', 'Z')):
                scale.prop(mapping.inputs['Scale'], 'default_value', index=i, text=label)
    if not mappings:
        body.separator(factor=0.4)
        body.label(text='Use the folder buttons to load texture maps.', icon='INFO')
    if context.space_data.type == 'VIEW_3D' and context.space_data.shading.type in {'SOLID', 'WIREFRAME'}:
        preview = layout.operator('wm.context_set_enum', text='Show Material Preview', icon='SHADING_TEXTURE')
        preview.data_path = 'space_data.shading.type'
        preview.value = 'MATERIAL'


classes = ()
