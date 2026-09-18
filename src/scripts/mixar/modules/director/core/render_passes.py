# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Temporary Blender render configuration for Director motion guides."""

from __future__ import annotations

import uuid

import bpy
from mathutils import Vector

from mixar.config.logging_config import get_logger

from .render_spec import render_frame_bounds


logger = get_logger(__name__)


def _safe_set(owner, name: str, value) -> None:
    try:
        setattr(owner, name, value)
    except (AttributeError, TypeError, ValueError):
        pass


def _property_snapshot(owner, names) -> dict:
    values = {}
    for name in names:
        if not hasattr(owner, name):
            continue
        value = getattr(owner, name)
        values[name] = (
            tuple(value)
            if hasattr(value, "__len__") and not isinstance(value, str)
            else value
        )
    return values


def snapshot_render_settings(scene, view_layer) -> dict:
    """Capture every scene setting temporarily changed by a guide render."""
    render = scene.render
    return {
        "scene": {
            "camera": scene.camera,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "frame_step": scene.frame_step,
            "frame_current": scene.frame_current,
            "use_nodes": scene.use_nodes,
            "compositing_node_group": getattr(
                scene,
                "compositing_node_group",
                None,
            ),
        },
        "eevee": _property_snapshot(
            scene.eevee,
            ("taa_render_samples",),
        ),
        "render": _property_snapshot(
            render,
            (
                "engine",
                "filepath",
                "resolution_percentage",
                "film_transparent",
                "use_compositing",
                "use_sequencer",
                "use_file_extension",
                "use_border",
                "use_crop_to_border",
                "use_stamp",
            ),
        ),
        "image": _property_snapshot(
            render.image_settings,
            ("media_type", "file_format", "color_mode", "color_depth"),
        ),
        "ffmpeg": _property_snapshot(
            render.ffmpeg,
            (
                "format",
                "codec",
                "constant_rate_factor",
                "ffmpeg_preset",
                "audio_codec",
            ),
        ),
        "shading": _property_snapshot(
            scene.display.shading,
            (
                "light",
                "color_type",
                "single_color",
                "background_type",
                "background_color",
                "show_shadows",
                "show_cavity",
                "show_specular_highlight",
                "show_object_outline",
            ),
        ),
        "view": {
            "view_transform": scene.view_settings.view_transform,
            "look": scene.view_settings.look,
            "use_pass_z": view_layer.use_pass_z,
        },
    }


def restore_render_settings(
    scene,
    view_layer,
    saved: dict,
    temp_group_name: str = "",
) -> None:
    """Restore a snapshot and remove any temporary depth compositor."""
    scene_values = saved["scene"]
    if hasattr(scene, "compositing_node_group"):
        _safe_set(
            scene,
            "compositing_node_group",
            scene_values["compositing_node_group"],
        )
    _safe_set(scene, "use_nodes", scene_values["use_nodes"])
    for name, value in saved["render"].items():
        _safe_set(scene.render, name, value)
    for name, value in saved.get("eevee", {}).items():
        _safe_set(scene.eevee, name, value)
    for name, value in saved["image"].items():
        _safe_set(scene.render.image_settings, name, value)
    for name, value in saved["ffmpeg"].items():
        _safe_set(scene.render.ffmpeg, name, value)
    for name, value in saved["shading"].items():
        _safe_set(scene.display.shading, name, value)
    _safe_set(scene.view_settings, "view_transform", saved["view"]["view_transform"])
    _safe_set(scene.view_settings, "look", saved["view"]["look"])
    _safe_set(view_layer, "use_pass_z", saved["view"]["use_pass_z"])
    _safe_set(scene, "camera", scene_values["camera"])
    _safe_set(scene, "frame_start", scene_values["frame_start"])
    _safe_set(scene, "frame_end", scene_values["frame_end"])
    _safe_set(scene, "frame_step", scene_values["frame_step"])
    scene.frame_set(scene_values["frame_current"])
    if not temp_group_name:
        return
    group = bpy.data.node_groups.get(temp_group_name)
    if group is not None:
        try:
            bpy.data.node_groups.remove(group)
        except Exception:
            logger.exception("Could not remove temporary Director compositor")


def _sample_depth_range(scene, camera, frame_start: int, frame_end: int):
    current = scene.frame_current
    positive_depths = []
    span = max(1, frame_end - frame_start)
    step = max(1, (span + 30) // 31)
    frames = list(range(frame_start, frame_end + 1, step))
    if frames[-1] != frame_end:
        frames.append(frame_end)
    try:
        for frame in frames:
            scene.frame_set(frame)
            depsgraph = bpy.context.evaluated_depsgraph_get()
            evaluated_camera = camera.evaluated_get(depsgraph)
            camera_matrix = evaluated_camera.matrix_world
            camera_location = camera_matrix.to_translation()
            camera_forward = camera_matrix.to_quaternion() @ Vector((0.0, 0.0, -1.0))
            for obj in scene.objects:
                if obj.type != 'MESH' or obj.hide_render:
                    continue
                evaluated = obj.evaluated_get(depsgraph)
                for corner in evaluated.bound_box:
                    world_corner = evaluated.matrix_world @ Vector(corner)
                    depth = (world_corner - camera_location).dot(camera_forward)
                    if depth > 0.0:
                        positive_depths.append(float(depth))
    finally:
        scene.frame_set(current)

    clip_start = max(float(camera.data.clip_start), 0.0001)
    clip_end = max(float(camera.data.clip_end), clip_start + 1.0)
    if not positive_depths:
        return clip_start, clip_end
    depth_min = max(clip_start, min(positive_depths))
    depth_max = min(clip_end, max(positive_depths))
    depth_span = max(depth_max - depth_min, 0.001)
    padding = depth_span * 0.05
    return max(clip_start, depth_min - padding), min(clip_end, depth_max + padding)


def _depth_compositor(scene, view_layer, depth_min: float, depth_max: float) -> str:
    tree = bpy.data.node_groups.new(
        f"Mixar Director Depth {uuid.uuid4().hex[:8]}",
        "CompositorNodeTree",
    )
    tree.interface.new_socket(
        name="Image",
        in_out='OUTPUT',
        socket_type='NodeSocketColor',
    )
    render_layers = tree.nodes.new(type='CompositorNodeRLayers')
    render_layers.layer = view_layer.name
    mapping = tree.nodes.new(type='ShaderNodeMapRange')
    mapping.inputs[1].default_value = depth_min
    mapping.inputs[2].default_value = max(depth_max, depth_min + 0.001)
    mapping.inputs[3].default_value = 1.0
    mapping.inputs[4].default_value = 0.0
    _safe_set(mapping, "clamp", True)
    output = tree.nodes.new(type='NodeGroupOutput')
    output.is_active_output = True
    tree.links.new(render_layers.outputs['Depth'], mapping.inputs[0])
    tree.links.new(mapping.outputs[0], output.inputs['Image'])
    scene.use_nodes = True
    scene.compositing_node_group = tree
    return tree.name


def _configure_common(scene, shot, frame_start: int, frame_end: int, path: str) -> None:
    render = scene.render
    scene.camera = shot.camera
    scene.frame_start = frame_start
    scene.frame_end = frame_end
    scene.frame_step = 1
    scene.frame_set(frame_start)
    render.engine = 'BLENDER_WORKBENCH'
    render.filepath = path
    render.resolution_percentage = int(shot.render_resolution_percentage)
    render.film_transparent = False
    render.use_compositing = False
    render.use_sequencer = False
    render.use_file_extension = True
    render.use_border = False
    render.use_crop_to_border = False
    render.use_stamp = False
    # Blender 5 filters file formats by media type. FFMPEG is unavailable
    # while the settings remain in their default IMAGE namespace.
    render.image_settings.media_type = 'VIDEO'
    render.image_settings.file_format = 'FFMPEG'
    render.image_settings.color_mode = 'RGB'
    render.image_settings.color_depth = '8'
    render.ffmpeg.format = 'MPEG4'
    render.ffmpeg.codec = 'H264'
    _safe_set(render.ffmpeg, "constant_rate_factor", 'MEDIUM')
    _safe_set(render.ffmpeg, "ffmpeg_preset", 'GOOD')
    _safe_set(render.ffmpeg, "audio_codec", 'NONE')

    shading = scene.display.shading
    shading.light = 'STUDIO'
    shading.background_type = 'VIEWPORT'
    shading.background_color = (0.025, 0.025, 0.025)
    shading.show_shadows = True
    shading.show_cavity = True
    _safe_set(shading, "show_object_outline", False)


def _scene_has_splats(scene) -> bool:
    """True when any mesh carries the KIRI splat geometry-nodes modifier."""
    from mixar.modules.moodboard.core.splat_render_camera import scene_has_splats

    return scene_has_splats(scene)


def configure_render_pass(scene, view_layer, shot, kind: str, path: str) -> str:
    """Configure one Workbench or normalized-depth movie pass."""
    frame_start, frame_end = render_frame_bounds(beat.frame for beat in shot.beats)
    _configure_common(scene, shot, frame_start, frame_end, path)
    view_layer.use_pass_z = kind == "DEPTH"
    shading = scene.display.shading
    if kind == "BEAUTY":
        shading.color_type = 'MATERIAL'
        shading.show_specular_highlight = True
        if _scene_has_splats(scene):
            # Workbench cannot evaluate the splat material's attribute-driven
            # node tree — gaussians come out as flat grey cards. EEVEE renders
            # them correctly (the splat_render_camera handlers push per-frame
            # camera matrices into the GN during the render, and splat scenes
            # run with Lock Interface). Modest TAA samples: this is a guide
            # video, and gaussian quads are emission-flat anyway.
            scene.render.engine = 'BLENDER_EEVEE'
            scene.eevee.taa_render_samples = 16
        return ""
    shading.color_type = 'SINGLE'
    shading.single_color = (0.58, 0.58, 0.58)
    shading.show_specular_highlight = False
    if kind != "DEPTH":
        return ""
    scene.view_settings.view_transform = 'Raw'
    _safe_set(scene.view_settings, "look", 'None')
    depth_min, depth_max = _sample_depth_range(
        scene,
        shot.camera,
        frame_start,
        frame_end,
    )
    scene.render.use_compositing = True
    return _depth_compositor(scene, view_layer, depth_min, depth_max)
