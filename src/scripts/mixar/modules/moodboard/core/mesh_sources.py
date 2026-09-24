# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Scene membership, not a retained datablock, makes a mesh reference usable."""


def is_scene_mesh(scene, obj) -> bool:
    try:
        return (obj is not None and obj.type == 'MESH'
                and scene.objects.get(obj.name) == obj)
    except ReferenceError:
        return False


def mesh_input_objects(context, node):
    """Validate connected meshes before selection, export or queue mutation."""
    from .node_graph import asset_node_by_id, input_source_object_names

    scene = context.scene
    for link in scene.mixie_moodboard_links:
        if link.to_node_id != node.node_id:
            continue
        source = asset_node_by_id(scene, link.from_node_id)
        if source is None or not source.scene_mesh_reference:
            continue
        obj = source.preview_object
        if is_scene_mesh(scene, obj):
            continue
        name = obj.name if obj is not None else source.object_names
        if name:
            raise ValueError(
                f'Mesh "{name}" was removed from this scene. '
                'Select another mesh on its Moodboard node.'
            )
        raise ValueError('No mesh selected. Use Select Mesh on the connected Moodboard node.')

    names = input_source_object_names(scene, node)
    if not names:
        raise ValueError('Connect a mesh node and select a scene mesh before generating.')
    objects = []
    for name in names:
        obj = scene.objects.get(name)
        if obj is None:
            raise ValueError(
                f'Mesh "{name}" is no longer in this scene. '
                'Restore it or connect another mesh node.'
            )
        if context.view_layer.objects.get(name) != obj:
            raise ValueError(
                f'Mesh "{name}" is unavailable in the current view layer. '
                'Enable its collection in the Outliner or choose another mesh.'
            )
        objects.append(obj)
    if not any(obj.type == 'MESH' for obj in objects):
        raise ValueError('Connect a mesh node and select a scene mesh before generating.')
    return objects
