# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later

"""Scene bindings for the Zen toolbar. Drawing never changes scene data."""

import bpy


def render_samples_binding(scene, target="RENDER"):
    """Bind the selected engine's independent render or viewport setting."""
    viewport = target == "VIEWPORT"
    engine = scene.render.engine
    if engine == "CYCLES" and hasattr(scene, "cycles"):
        return scene.cycles, "preview_samples" if viewport else "samples"
    if engine == "BLENDER_EEVEE" and hasattr(scene, "eevee"):
        return scene.eevee, "taa_samples" if viewport else "taa_render_samples"
    if engine == "BLENDER_WORKBENCH":
        return scene.display, "viewport_aa" if viewport else "render_aa"
    return None


def sky_enabled(scene):
    state = getattr(scene, "mixar_zen_sky", None)
    return bool(state and state.sky_world and scene.world == state.sky_world)


def set_sky_enabled(scene, enabled):
    """Swap a dedicated sky world in/out without editing the user's world.

    Both pointers are saved in the scene and participate in native undo. The
    active world is authoritative if the user changes it through another UI.
    """
    state = scene.mixar_zen_sky
    if sky_enabled(scene) == enabled:
        return
    if not enabled:
        scene.world = state.previous_world
        return

    world = state.sky_world
    if world is None:
        world = bpy.data.worlds.new("Zen Sky")
        try:
            # Blender 5.2 worlds always have nodes; earlier builds need this.
            if not world.use_nodes:
                world.use_nodes = True
            tree = world.node_tree
            tree.nodes.clear()
            output = tree.nodes.new("ShaderNodeOutputWorld")
            background = tree.nodes.new("ShaderNodeBackground")
            sky = tree.nodes.new("ShaderNodeTexSky")
            sky.location = (-520, 0)
            background.location = (-240, 0)
            output.location = (0, 0)
            tree.links.new(sky.outputs["Color"], background.inputs["Color"])
            tree.links.new(background.outputs["Background"], output.inputs["Surface"])
        except Exception:
            bpy.data.worlds.remove(world)
            raise
        state.sky_world = world
    state.previous_world = scene.world
    scene.world = world
