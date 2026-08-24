# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Apply a still image as the scene world environment map.

Panorama / HDRI stills from Image Gen or the moodboard become the world's
environment texture. Movies are refused — Blender's world shader samples a
still. The node graph is rebuilt in place so the change is one undo step.
"""

from __future__ import annotations


def apply_image_as_world(image, *, world_name: str = "Mixar World"):
    """Wire *image* into ``scene.world`` as an environment texture.

    Returns the world datablock. Raises ``ValueError`` when *image* is
    missing or a movie.
    """
    import bpy

    from .media_utils import is_video_image

    if image is None:
        raise ValueError("Select a still image first.")
    if is_video_image(image):
        raise ValueError("World environments need a still image, not a video.")

    scene = bpy.context.scene
    world = scene.world
    if world is None:
        world = bpy.data.worlds.new(world_name)
        scene.world = world
    world.use_nodes = True
    nodes = world.node_tree.nodes
    links = world.node_tree.links
    nodes.clear()

    output = nodes.new("ShaderNodeOutputWorld")
    background = nodes.new("ShaderNodeBackground")
    env = nodes.new("ShaderNodeTexEnvironment")
    tex_coord = nodes.new("ShaderNodeTexCoord")
    mapping = nodes.new("ShaderNodeMapping")
    env.image = image
    links.new(tex_coord.outputs["Generated"], mapping.inputs["Vector"])
    links.new(mapping.outputs["Vector"], env.inputs["Vector"])
    links.new(env.outputs["Color"], background.inputs["Color"])
    links.new(background.outputs["Background"], output.inputs["Surface"])
    return world


def selected_still_image(context):
    """First selected moodboard still, or None."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    from .media_utils import is_still_item

    for item in getattr(scene, "mixie_moodboard_images", ()):
        if getattr(item, "selected", False) and is_still_item(item):
            return getattr(item, "image", None)
    return None
