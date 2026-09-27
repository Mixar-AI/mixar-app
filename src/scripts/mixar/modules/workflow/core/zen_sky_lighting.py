# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Owned sky/HDRI node bindings; file failures never replace scene lighting."""

from pathlib import Path

import bpy

from .zen_scene import create_sky_world, sky_enabled


def sky_nodes(scene):
    world = scene.mixar_zen_sky.sky_world
    nodes = world.node_tree.nodes if world and world.node_tree else ()
    return {node.bl_idname: node for node in nodes}


def uses_hdri(scene):
    background = sky_nodes(scene).get("ShaderNodeBackground")
    return bool(background and any(link.from_node.bl_idname == "ShaderNodeTexEnvironment"
                                   for link in background.inputs["Color"].links))


def set_sky_source(scene, hdri):
    nodes = sky_nodes(scene)
    source = nodes.get("ShaderNodeTexEnvironment" if hdri else "ShaderNodeTexSky")
    background = nodes.get("ShaderNodeBackground")
    if source is None or background is None or (hdri and not source.image):
        raise RuntimeError("Add an HDRI first" if hdri else "Enable Sky Light first")
    tree = scene.mixar_zen_sky.sky_world.node_tree
    tree.links.new(source.outputs["Color"], background.inputs["Color"])


def load_hdri(scene, filepath):
    """Prepare a complete replacement before committing the undoable world swap."""
    path = Path(bpy.path.abspath(filepath))
    if path.suffix.lower() not in {".hdr", ".exr"} or not path.is_file():
        raise ValueError("Choose an existing .hdr or .exr environment image")
    image = bpy.data.images.load(str(path), check_existing=False)
    world = None
    try:
        # Reading size forces Blender to decode the lazily loaded image.
        if not all(image.size) or not image.has_data:
            raise ValueError("The HDRI could not be decoded")
        state = scene.mixar_zen_sky
        world = state.sky_world.copy() if state.sky_world else create_sky_world()
        tree = world.node_tree
        def node(kind):
            return next((n for n in tree.nodes if n.bl_idname == kind), None) or tree.nodes.new(kind)
        environment = node("ShaderNodeTexEnvironment")
        environment.image = image
        environment.projection = "EQUIRECTANGULAR"
        mapping = node("ShaderNodeMapping")
        coordinates = node("ShaderNodeTexCoord")
        environment.location, mapping.location, coordinates.location = (-520, -240), (-760, -240), (-980, -240)
        tree.links.new(coordinates.outputs["Generated"], mapping.inputs["Vector"])
        tree.links.new(mapping.outputs["Vector"], environment.inputs["Vector"])
        tree.links.new(environment.outputs["Color"], node("ShaderNodeBackground").inputs["Color"])
        # Keep the pre-activation world across replacements made while ON.
        if not sky_enabled(scene):
            state.previous_world = scene.world
        state.sky_world = world
        scene.world = world
    except Exception:
        if world is not None:
            bpy.data.worlds.remove(world)
        bpy.data.images.remove(image)
        raise
