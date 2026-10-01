# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""``use_case`` presets for the agent's ``export_scene`` tool (contract §4).

``PRESETS[use_case][exporter]`` holds the exporter keyword arguments that
differ per target engine; ``COMMON`` holds what every preset shares
(selection only, meshes + armatures, copied/embedded textures, never
cameras or lights). ``preset_report`` summarises the applied preset for
the result dict the backend shows the user.
"""

from __future__ import annotations

USE_CASES = ("unreal", "unity", "godot", "web", "ar", "other")

# What every preset shares, keyed by exporter family.
COMMON = {
    "fbx": {
        "use_selection": True, "object_types": {"MESH", "ARMATURE"},
        "path_mode": "COPY", "embed_textures": True, "use_mesh_modifiers": True,
        "axis_forward": "-Z", "axis_up": "Y", "apply_unit_scale": True,
        "add_leaf_bones": False, "use_armature_deform_only": True,
    },
    "gltf": {
        # use_selection alone still walks EVERY scene: an object selected in
        # another scene lands in the file as a second glTF scene.
        "use_selection": True, "use_active_scene": True,
        "export_cameras": False, "export_lights": False,
        "export_texcoords": True, "export_normals": True, "export_materials": "EXPORT",
        "export_image_format": "AUTO", "export_draco_mesh_compression_enable": False,
        "export_yup": True,
    },
    "obj": {
        "export_selected_objects": True, "export_uv": True, "export_normals": True,
        "export_materials": True, "path_mode": "COPY", "apply_modifiers": True,
    },
    "usd": {
        "selected_objects_only": True, "export_materials": True, "export_uvmaps": True,
        "export_normals": True, "export_armatures": True,
        "export_cameras": False, "export_lights": False, "relative_paths": True,
    },
    # Geometry only. Z-up / Y-forward is what slicers expect; the scene unit
    # is ignored so ``global_scale`` (``stl_kwargs``) is the only multiplier.
    "stl": {
        "export_selected_objects": True, "apply_modifiers": True, "use_batch": False,
        "use_scene_unit": False, "forward_axis": "Y", "up_axis": "Z",
        "global_scale": 1.0, "ascii_format": False,
    },
}

_USD_YUP = {
    "convert_orientation": True,
    "export_global_forward_selection": "NEGATIVE_Z",
    "export_global_up_selection": "Y",
}
_FBX_UNITY = {
    "apply_scale_options": "FBX_SCALE_UNITS", "bake_anim_use_all_bones": False,
    "use_tspace": True, "mesh_smooth_type": "FACE",
}
_GLTF_GODOT = {"export_apply": True, "export_tangents": True}

PRESETS = {
    "unreal": {
        "fbx": {
            "apply_scale_options": "FBX_SCALE_NONE", "bake_anim_use_all_bones": True,
            "bake_anim_simplify_factor": 0.0, "mesh_smooth_type": "FACE",
            "use_tspace": True, "primary_bone_axis": "Y", "secondary_bone_axis": "X",
        },
        "gltf": {"export_apply": False},
        "usd": dict(_USD_YUP),
    },
    "unity": {"fbx": dict(_FBX_UNITY), "gltf": {"export_apply": False}, "usd": dict(_USD_YUP)},
    "godot": {"fbx": dict(_FBX_UNITY), "gltf": dict(_GLTF_GODOT), "usd": dict(_USD_YUP)},
    "web": {"fbx": dict(_FBX_UNITY), "gltf": dict(_GLTF_GODOT), "usd": dict(_USD_YUP)},
    "ar": {
        "fbx": {"apply_scale_options": "FBX_SCALE_ALL"},
        "gltf": dict(_GLTF_GODOT),
        "usd": {**_USD_YUP, "export_textures_mode": "NEW", "overwrite_textures": True},
    },
    "other": {
        "fbx": {"apply_scale_options": "FBX_SCALE_ALL"},
        "gltf": dict(_GLTF_GODOT),
        "usd": {},
    },
}

_FAMILY = {"fbx": "fbx", "glb": "gltf", "gltf": "gltf", "obj": "obj",
           "usd": "usd", "usdc": "usd", "usda": "usd", "usdz": "usd", "stl": "stl"}
STL_SCALE_RANGE = (1.0e-6, 1.0e6)  # wm.stl_export ``global_scale`` hard range


def exporter_family(fmt: str) -> str:
    return _FAMILY.get(str(fmt or "").lower().lstrip("."), "gltf")


def preset_kwargs(use_case: str, fmt: str) -> dict:
    """Merged exporter kwargs for ``use_case`` (unknown → ``other``)."""
    family = exporter_family(fmt)
    use_case = str(use_case or "other").lower()
    if use_case not in PRESETS:
        use_case = "other"
    kwargs = dict(COMMON[family])
    kwargs.update(PRESETS[use_case].get(family, {}))
    if fmt == "usdz":
        kwargs.setdefault("export_textures_mode", "NEW")
    return kwargs


def stl_kwargs(spec: dict) -> dict:
    """``spec["stl"] = {"scale": float, "ascii": bool}`` → ``wm.stl_export``
    kwargs; absent keys default to scale 1.0, binary. A scale outside the
    operator's range raises ValueError (never silently clamped)."""
    options = spec.get("stl") or {}
    if not isinstance(options, dict):
        raise ValueError("stl options must be an object")
    scale = options.get("scale")
    scale = 1.0 if scale is None else float(scale)
    low, high = STL_SCALE_RANGE
    if not low <= scale <= high:  # also rejects NaN
        raise ValueError(f"STL scale must be between {low:g} and {high:g}")
    return {"global_scale": scale, "ascii_format": bool(options.get("ascii", False))}


def preset_report(use_case: str, fmt: str, kwargs: dict, animation_mode: str) -> dict:
    """Content-free summary of the preset that ran, for ``result.preset``."""
    family = exporter_family(fmt)
    use_case = str(use_case or "other").lower()
    report = {
        "use_case": use_case if use_case in PRESETS else "other",
        "exporter": family,
        "axis_forward": None, "axis_up": None, "scale": None,
        "leaf_bones": None, "animation_mode": animation_mode,
        "tangents": None, "apply_modifiers": None, "draco": None,
        "image_format": None, "embed_textures": None, "active_scene_only": True,
    }
    if family == "fbx":
        report.update(
            axis_forward=kwargs.get("axis_forward"), axis_up=kwargs.get("axis_up"),
            scale=kwargs.get("apply_scale_options"), leaf_bones=kwargs.get("add_leaf_bones"),
            tangents=kwargs.get("use_tspace", False),
            apply_modifiers=kwargs.get("use_mesh_modifiers"),
            embed_textures=kwargs.get("embed_textures"),
        )
    elif family == "gltf":
        report.update(
            axis_forward="-Z", axis_up="Y" if kwargs.get("export_yup", True) else "Z",
            scale="meters", leaf_bones=False,
            tangents=kwargs.get("export_tangents", False),
            apply_modifiers=kwargs.get("export_apply", False),
            draco=kwargs.get("export_draco_mesh_compression_enable", False),
            image_format=kwargs.get("export_image_format"),
            embed_textures=fmt == "glb",
            active_scene_only=bool(kwargs.get("use_active_scene", False)),
        )
    elif family == "usd":
        yup = bool(kwargs.get("convert_orientation"))
        report.update(
            axis_forward="-Z" if yup else "Y", axis_up="Y" if yup else "Z",
            scale="meters", embed_textures=fmt == "usdz",
            apply_modifiers=True,
        )
    elif family == "stl":
        report.update(
            axis_forward=kwargs.get("forward_axis"), axis_up=kwargs.get("up_axis"),
            scale=kwargs.get("global_scale"), apply_modifiers=kwargs.get("apply_modifiers"),
            embed_textures=False, ascii=bool(kwargs.get("ascii_format")),
        )
    else:
        report.update(axis_forward="-Z", axis_up="Y", scale="meters",
                      apply_modifiers=kwargs.get("apply_modifiers", True),
                      embed_textures=False)
    return report
