# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""The card's settings → the export lane's ``spec`` and exporter overrides.

The card's 3D settings always hold the values the exporter will run with:
picking a "Made for" engine (or a target) loads that ``use_case`` preset's
values into them (`sync_preset`), and the export passes them back as
explicit overrides (`overrides`), so what the user sees is what is written.
``p`` is the card's property group (or any object with the same attributes,
which keeps this module testable without ``bpy``).
"""

from __future__ import annotations

from mixar.modules.space_mixie_chat.core.export_presets import preset_kwargs

from .. import constants as C
from . import targets

USD_Y_UP = {"convert_orientation": True, "export_global_forward_selection": "NEGATIVE_Z",
            "export_global_up_selection": "Y"}


def model_format(p) -> str:
    return targets.model_format(p.target, p.gltf_file, p.usd_file)


def model_spec(p, file_stem: str) -> dict:
    """The export lane's spec (`agent_export.export_to_path`)."""
    fmt = model_format(p)
    spec = {
        "format": fmt,
        "use_case": p.engine if p.target != C.STL else "other",
        "target_scope": "selected" if p.scope == 'SELECTED' else "scene",
        # None exports every clip; an empty list exports none.
        "animations": None if p.animation == 'ALL' else [],
        "suggested_filename": file_stem,
        "destination": "export_card",
    }
    if fmt == "stl":
        spec["stl"] = {"scale": C.STL_UNIT_SCALE.get(p.stl_units, 1000.0) * float(p.stl_scale),
                       "ascii": bool(p.stl_ascii)}
    return spec


def overrides(p) -> dict:
    """Exporter kwargs the card's settings pin (on top of the preset)."""
    fmt = model_format(p)
    if fmt in ("glb", "gltf"):
        return {
            "export_cameras": bool(p.cameras_lights),
            "export_lights": bool(p.cameras_lights),
            "export_image_format": p.texture_format,
            "export_draco_mesh_compression_enable": bool(p.draco),
            "export_apply": bool(p.apply_modifiers),
            "export_yup": bool(p.y_up),
        }
    if fmt == "fbx":
        return {
            "embed_textures": bool(p.fbx_embed),
            "path_mode": "COPY",
            "apply_scale_options": p.fbx_scale,
            "add_leaf_bones": bool(p.leaf_bones),
            "mesh_smooth_type": p.smoothing,
            "use_mesh_modifiers": bool(p.apply_modifiers),
        }
    if fmt in ("usdz", "usdc"):
        orientation = dict(USD_Y_UP) if p.y_up else {"convert_orientation": False}
        return {**orientation, "export_cameras": bool(p.cameras_lights),
                "export_lights": bool(p.cameras_lights)}
    if fmt == "obj":
        return {"path_mode": "COPY" if p.obj_copy_textures else "AUTO",
                "apply_modifiers": bool(p.apply_modifiers)}
    return {}


def sync_preset(p) -> None:
    """Load the current engine's preset values into the card's settings."""
    fmt = model_format(p)
    if not fmt or fmt == "stl":
        return
    kwargs = preset_kwargs(p.engine, fmt)
    if fmt in ("glb", "gltf"):
        p.cameras_lights = bool(kwargs.get("export_cameras", False))
        image_format = str(kwargs.get("export_image_format", "AUTO"))
        p.texture_format = image_format if image_format in ('AUTO', 'JPEG', 'WEBP', 'NONE') \
            else 'AUTO'
        p.draco = bool(kwargs.get("export_draco_mesh_compression_enable", False))
        p.apply_modifiers = bool(kwargs.get("export_apply", False))
        p.y_up = bool(kwargs.get("export_yup", True))
    elif fmt == "fbx":
        p.fbx_embed = bool(kwargs.get("embed_textures", True))
        scale = str(kwargs.get("apply_scale_options", "FBX_SCALE_NONE"))
        p.fbx_scale = scale if scale in ('FBX_SCALE_NONE', 'FBX_SCALE_UNITS', 'FBX_SCALE_ALL') \
            else 'FBX_SCALE_NONE'
        p.leaf_bones = bool(kwargs.get("add_leaf_bones", False))
        smooth = str(kwargs.get("mesh_smooth_type", "FACE"))
        p.smoothing = smooth if smooth in ('FACE', 'EDGE', 'OFF') else 'FACE'
        p.apply_modifiers = bool(kwargs.get("use_mesh_modifiers", True))
    elif fmt in ("usdz", "usdc"):
        p.y_up = bool(kwargs.get("convert_orientation", False))
        p.cameras_lights = bool(kwargs.get("export_cameras", False))
    elif fmt == "obj":
        p.obj_copy_textures = kwargs.get("path_mode", "COPY") == "COPY"
        p.apply_modifiers = bool(kwargs.get("apply_modifiers", True))


def render_options(p) -> dict:
    """`scene_render.jobs.start` options for an Image / Video target."""
    renderer = 'CYCLES' if p.renderer == 'CYCLES' else 'EEVEE'
    options = {
        "engine": renderer.lower(),
        "samples": C.RENDER_SAMPLES[renderer].get(p.quality, 64),
        "width": int(p.width), "height": int(p.height),
        "camera": p.camera if p.camera not in ('', 'NONE') else "",
    }
    if p.target == C.IMAGE:
        options.update(image_format=p.render_format, transparent=bool(p.transparent))
    else:
        options.update(frame_start=int(p.frame_start), frame_end=int(p.frame_end),
                       fps=int(p.fps))
    return options
