# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Run explicitly after rendering; the render operator never calls this script.

    from mixar.modules.common.render_visibility.collect import create_collection
    collection = create_collection(bpy.context.scene)

Running this file in Blender's Text Editor also creates the collection.
"""

from mixar.modules.common.render_visibility.constants import COLLECTION_NAME
from mixar.modules.common.render_visibility.result import read_result, resolve_meshes


def create_collection(scene=None, name=COLLECTION_NAME):
    import bpy

    scene = scene or bpy.context.scene
    result = read_result(scene)
    objects = resolve_meshes(scene, result)
    collection = bpy.data.collections.new(name)
    try:
        scene.collection.children.link(collection)
        for obj in objects:
            collection.objects.link(obj)
    except Exception:
        bpy.data.collections.remove(collection)
        raise
    return collection


if __name__ == "__main__":
    create_collection()
