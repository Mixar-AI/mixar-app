# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Deterministic Eevee fixture; creates a NEW scene without deleting user objects.

Run in the Text Editor to prepare the scene, or call build_scene() from the QA harness.
Camera looks along +Y; the opaque blocker hides the primitives behind and inside it.
"""

import math


def build_scene():
    import bpy

    scene = bpy.data.scenes.new("Visibility QA")
    bpy.context.window.scene = scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = 512
    scene.render.resolution_y = 384
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.use_compositing = False
    scene.render.use_sequencer = False
    scene.eevee.taa_render_samples = 32
    scene.world = bpy.data.worlds.new("Visibility QA World")
    scene.world.use_nodes = True
    scene.world.node_tree.nodes.get("Background").inputs[0].default_value = (0.12, 0.12, 0.12, 1)

    def material(name, color, alpha=1):
        mat = bpy.data.materials.new(name)
        mat.use_nodes = True
        mat.surface_render_method = "DITHERED"
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        bsdf.inputs["Base Color"].default_value = (*color, 1)
        bsdf.inputs["Roughness"].default_value = 0.7
        bsdf.inputs["Alpha"].default_value = alpha
        return mat

    blue = material("QA blue", (0.1, 0.3, 0.8))
    orange = material("QA orange", (0.9, 0.25, 0.03))
    green = material("QA green", (0.05, 0.7, 0.15))
    transparent = material("QA transparent wall", (0.5, 0.7, 0.9), 0.3)

    def cube(name, location, scale, mat):
        bpy.ops.mesh.primitive_cube_add(size=2, location=location)
        obj = bpy.context.object
        obj.name = name
        obj.scale = scale
        obj.data.materials.append(mat)
        return obj

    blocker = cube("QA_Blocker", (-2, 0, 0), (1.3, 0.8, 1.3), blue)
    behind = cube("QA_HiddenBehind", (-2, 3, 0), (0.5, 0.5, 0.5), orange)
    inside = cube("QA_HiddenInside", (-2, 0, 0), (0.3, 0.3, 0.3), green)
    partial = cube("QA_Partial", (-0.65, 2, 0.1), (0.55, 0.55, 0.55), orange)
    outside = cube("QA_Outside", (20, 0, 0), (1, 1, 1), green)
    wall = cube("QA_TransparentWall", (2, -0.3, 0), (1.1, 0.04, 1.3), transparent)
    through = cube("QA_ThroughTransparency", (2, 1.5, 0), (0.7, 0.5, 0.7), green)
    hidden_render = cube("QA_RenderDisabled", (0, -2, 1.6), (0.3, 0.3, 0.3), orange)
    hidden_render.hide_render = True

    camera_data = bpy.data.cameras.new("QA Camera")
    camera = bpy.data.objects.new("QA Camera", camera_data)
    scene.collection.objects.link(camera)
    camera.location = (0, -12, 0)
    camera.rotation_euler = (math.pi / 2, 0, 0)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 9
    scene.camera = camera

    light_data = bpy.data.lights.new("QA Area", "AREA")
    light_data.energy = 1500
    light_data.shape = "DISK"
    light_data.size = 8
    light = bpy.data.objects.new("QA Area", light_data)
    scene.collection.objects.link(light)
    light.location = (0, -5, 4)
    light.rotation_euler = (math.radians(45), 0, 0)

    expected = [blocker, partial, wall, through]
    excluded = [behind, inside, outside, hidden_render]
    scene["visibility_qa_expected"] = [obj.name for obj in expected]
    scene["visibility_qa_excluded"] = [obj.name for obj in excluded]
    return scene


if __name__ == "__main__":
    build_scene()
