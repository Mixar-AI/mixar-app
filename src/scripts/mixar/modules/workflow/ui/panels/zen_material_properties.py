# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Three material controls, resolved from the active render output."""


def _source(socket):
    """Follow reroutes only; never guess a shader from an unrelated node."""
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


def draw_material_properties(layout, context, material):
    tree = material.node_tree
    if tree is None:
        layout.label(text="Edit this material in Engine Mode.", icon='INFO')
        return
    engine = context.scene.render.engine
    target = 'CYCLES' if engine == 'CYCLES' else 'EEVEE'
    output = tree.get_output_node(target) or tree.get_output_node('ALL')
    shader = _source(output.inputs.get('Surface')) if output else None
    if shader is None or shader.bl_idname != 'ShaderNodeBsdfPrincipled':
        layout.label(text="Edit this material in Engine Mode.", icon='INFO')
        return
    body = layout.column()
    body.enabled = material.is_editable and tree.is_editable
    for name, label in (('Base Color', 'Color'), ('Roughness', 'Roughness'),
                        ('Metallic', 'Metallic')):
        socket = shader.inputs.get(name)
        if socket is None:
            continue
        if socket.is_linked:
            source = _source(socket)
            row = body.row()
            row.label(text=label)
            if source and source.bl_idname == 'ShaderNodeTexImage':
                row.prop_search(source, 'image', context.blend_data, 'images', text='')
            else:
                row.label(text="Driven by nodes", icon='NODETREE')
        else:
            body.prop(socket, 'default_value', text=label)


classes = ()
