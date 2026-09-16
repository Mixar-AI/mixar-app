# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Deterministic CAD edge-case scene; usable by background Blender and GUI QA.

Creates a NEW scene and owns only its fixture IDs. Never resets factory state or
opens/saves a user file. The caller decides when to restore the previous scene.
"""

import math
import uuid

import bpy


VERTICES = [(-1, -1, -1), (-1, -1, 1), (-1, 1, -1), (-1, 1, 1),
            (1, -1, -1), (1, -1, 1), (1, 1, -1), (1, 1, 1)]
FACES = [(0, 4, 6, 2), (1, 3, 7, 5), (0, 1, 5, 4),
         (2, 6, 7, 3), (0, 2, 3, 1), (4, 5, 7, 6)]


def build_fixture():
    token = uuid.uuid4().hex[:8]
    previous_scene = bpy.context.window.scene
    scene = bpy.data.scenes.new("CAD QA " + token)
    bpy.context.window.scene = scene
    root = bpy.data.collections.new("Vehicle renamed " + token)
    scene.collection.children.link(root)
    nested = bpy.data.collections.new("Assembly, door " + token)
    root.children.link(nested)
    outside = bpy.data.collections.new("Outside scope " + token)
    scene.collection.children.link(outside)
    objects = {}

    def mesh(name, location, dimensions=(0.8, 0.5, 0.3), faces=None, collection=None):
        data = bpy.data.meshes.new("QA mesh " + name)
        vertices = [tuple(co[i] * dimensions[i] / 2 for i in range(3))
                    for co in VERTICES]
        data.from_pydata(vertices, [], FACES if faces is None else faces)
        data.update()
        obj = bpy.data.objects.new(name, data)
        (collection or nested).objects.link(obj)
        obj.location = location
        objects[name] = obj
        return obj

    names = ["HEADLINER", "STEERING WHEEL", "WHEELHOUSE PANEL", "SHOCK ABS",
             "ENGINE BLOCK", "RADIATOR", "FUEL FILLER LID", "L1234567_BRAKE",
             "FR DOOR DESCRIPTION PLATE", "FR DOOR WINDOW GLASS",
             "Surface Assembly\\BRKT-ENGINE", "Copy (1) of L0638042_FOAM_PAD",
             "801529857R--A_002_NULL_FROZEN", "BODY SIDE PANEL"]
    for index, name in enumerate(names):
        mesh(name, (index % 5 * 1.2, index // 5 * 1.0, 0))
    mesh("DISTANCE SENSOR", (0, 3.3, 0), (0.02, 0.02, 0.02))
    mesh("801529858R--A_002_FR DOOR OUTER PANEL_FROZEN", (1.4, 3.3, 0),
         (2.0, 1.0, 0.001))
    base = mesh("QA topology A", (3, 3.3, 0))
    different_faces = list(FACES)
    different_faces[-1] = (4, 5, 6, 7)
    mesh("QA topology B", (3, 3.3, 0), faces=different_faces)
    rotated = mesh("QA rotated duplicate", (3, 3.3, 0))
    rotated.rotation_euler.z = math.pi / 4
    mesh("QA exact duplicate", (3, 3.3, 0))
    mesh("QA exact twin", (3, 3.3, 0))
    uv_variant = mesh("QA UV variant", (3, 3.3, 0))
    uv_variant.data.uv_layers.new(name="Different UV data")
    base.data.uv_layers.new(name="UVMap")
    parent = bpy.data.objects.new("QA transform parent", None)
    nested.objects.link(parent)
    parent.location = (4.2, 4.5, 0)
    child = mesh("FR DOOR OUTER PANEL", (0, 0, 0))
    child.parent = parent
    child.scale = (1.1, 0.9, 1.2)
    sentinel = mesh("OUTSIDE ENGINE BLOCK", (100, 100, 100), collection=outside)
    sentinel.hide_render = True
    sentinel.hide_viewport = True
    scene.unit_settings.system = "METRIC"
    scene.unit_settings.scale_length = 1.0
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.render.resolution_x = 800
    scene.render.resolution_y = 600
    scene.render.resolution_percentage = 100
    scene.display.shading.light = "STUDIO"
    scene.display.shading.color_type = "RANDOM"
    scene.display.shading.show_shadows = False
    camera_data = bpy.data.cameras.new("CAD QA camera " + token)
    camera = bpy.data.objects.new("CAD QA camera " + token, camera_data)
    scene.collection.objects.link(camera)
    camera.location = (8, -7, 11)
    from mathutils import Vector
    camera.rotation_euler = (Vector((2.5, 2.3, 0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = 9
    scene.camera = camera
    bpy.context.view_layer.update()
    return {"scene": scene, "previous_scene": previous_scene, "root": root,
            "nested": nested, "objects": objects, "sentinel": sentinel,
            "token": token, "source_filepath": bpy.data.filepath}


def snapshot(objects):
    """Capture externally observable mesh identity, topology, pose and visibility."""
    return {name: {"data": obj.data.as_pointer(),
                   "faces": [tuple(p.vertices) for p in obj.data.polygons],
                   "uv": [(layer.name, [tuple(loop.uv) for loop in layer.data])
                          for layer in obj.data.uv_layers],
                   "material_indices": [p.material_index for p in obj.data.polygons],
                   "world_vertices": [tuple(obj.matrix_world @ vertex.co)
                                      for vertex in obj.data.vertices],
                   "matrix": [tuple(row) for row in obj.matrix_world],
                   "collections": sorted(c.name for c in obj.users_collection),
                   "hide_render": obj.hide_render,
                   "hide_viewport": obj.hide_viewport}
            for name, obj in objects.items()}


def restore_active_scene(fixture):
    bpy.context.window.scene = fixture["previous_scene"]
