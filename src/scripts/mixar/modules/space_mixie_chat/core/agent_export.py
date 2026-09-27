# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Non-destructive Blender-native export execution for the agent's
``export_scene`` tool (export contract §1).

The backend never sees a path: the user picks the destination in
``mixie_chat.choose_export_location`` (a ``file_save`` question), which
parks it in ``export_destination`` under the session id; ``run_export``
pops it, exports the resolved meshes (plus the armatures they need) with
the native exporter under the ``use_case`` preset (``export_presets``) and
the ``animations`` clip selection (``export_clips``), verifies the written
file (``export_verify``) and reports a basename only. ``run_export_to`` is
the picker-less path into a folder KIND (downloads / library / temp).

``inspect_export`` runs the readiness preflight (``export_preflight``) so
the agent can offer "Fix and Export" (``repair_export``) before the picker.
"""

from __future__ import annotations

import os
import re
import time
from contextlib import contextmanager, nullcontext

import bpy

from .export_clips import animation_kwargs, clip_selection
from .export_destination import pop_destination
from .export_obj_textures import staged_obj_textures
from .export_preflight import (
    active_mixar_nodes,
    clear_repair_cache,
    material_images,
    repair_export,  # noqa: F401 — re-exported for the backend's repair call
    resolve_targets,
    run_preflight,
)
from .export_presets import PRESETS, preset_kwargs, preset_report  # noqa: F401
from .export_verify import file_clip_names, verify_export

EXTENSIONS = {"fbx": ".fbx", "glb": ".glb", "gltf": ".gltf", "obj": ".obj",
              "usd": ".usd", "usdc": ".usdc", "usdz": ".usdz"}
FOLDER_KINDS = ("downloads", "library", "temp")
MESH_NAME_LIMIT = 24


def _required_armatures(meshes) -> set:
    armatures = set()
    for mesh in meshes:
        if mesh.parent and mesh.parent.type == 'ARMATURE':
            armatures.add(mesh.parent)
        for modifier in mesh.modifiers:
            if modifier.type == 'ARMATURE' and modifier.object:
                armatures.add(modifier.object)
    return armatures


def _exporter(fmt: str):
    if fmt == "fbx":
        return bpy.ops.export_scene.fbx
    if fmt in ("glb", "gltf"):
        return bpy.ops.export_scene.gltf
    if fmt == "obj":
        return bpy.ops.wm.obj_export
    if fmt in ("usd", "usdc", "usdz"):
        return bpy.ops.wm.usd_export
    raise ValueError(f"Unsupported export format: {fmt}")


def _run_operator(fmt: str, filepath: str, use_case: str, animations,
                  overrides: dict | None = None) -> tuple[set, dict, str, str]:
    """Run the native exporter under the preset; returns
    ``(status, kwargs, animation_mode, warning)``."""
    kwargs = preset_kwargs(use_case, fmt)
    anim, mode, warning = animation_kwargs(fmt, animations)
    kwargs.update(anim)
    kwargs.update(overrides or {})
    if fmt in ("glb", "gltf"):
        kwargs["export_format"] = 'GLB' if fmt == "glb" else 'GLTF_SEPARATE'
    status = _exporter(fmt)(filepath=filepath, **kwargs)
    return status, kwargs, mode, warning


@contextmanager
def _temporary_export_materials(meshes):
    """Swap every Mixar slot to a Principled/image material for export."""
    from mixar.modules.paint.core.asset_export.bake_and_assign import (
        create_export_material,
    )

    assignments, created = [], []
    try:
        for obj in meshes:
            original_index = obj.active_material_index
            try:
                for index, material in enumerate(list(obj.data.materials)):
                    nodes = active_mixar_nodes(material)
                    if not nodes:
                        continue
                    obj.active_material_index = index
                    export_material = create_export_material(
                        obj, nodes[0].node_tree.mp, nodes[0].node_tree,
                    )
                    if export_material:
                        assignments.append((obj, index, material))
                        created.append(export_material)
            finally:
                obj.active_material_index = original_index
        yield
    finally:
        for obj, index, material in reversed(assignments):
            try:
                obj.data.materials[index] = material
            except Exception:
                pass
        for material in created:
            try:
                if material.users == 0:
                    bpy.data.materials.remove(material)
            except Exception:
                pass


def scrub_error(exc: BaseException) -> str:
    """Blender's exporters echo absolute paths; drop every path-like word."""
    words = str(exc).replace("\n", " ").split(" ")
    clean = " ".join(w for w in words if "/" not in w and "\\" not in w)
    return clean.strip()[:200] or exc.__class__.__name__


def _images_expected(meshes) -> int:
    images = set()
    for mesh in meshes:
        for material in getattr(mesh.data, "materials", ()) or ():
            for image in material_images(material):
                images.add(id(image))
    return len(images)


def _telemetry(context, fmt, spec, *, success, extension="", extra=None, started=None):
    try:
        from mixar.modules.common.analytics.export_events import capture_export
        properties = {
            "via": "agent", "tool": "export_scene",
            "scope": str(spec.get("target_scope") or "scene"),
            "use_case": str(spec.get("use_case") or "other"),
            "destination_kind": str(spec.get("destination") or "ask"),
        }
        if started is not None:
            properties["duration_ms"] = int((time.perf_counter() - started) * 1000)
        properties.update(extra or {})
        capture_export(context, export_format=fmt, success=success,
                       extension=extension, extra=properties)
    except Exception:
        pass


def _telemetry_initiated(context, fmt):
    try:
        from mixar.modules.common.analytics.export_events import capture_export_initiated
        capture_export_initiated(context, fmt, via="agent", tool="export_scene")
    except Exception:
        pass


def run_export(session_id: str, spec: dict) -> dict:
    """Consume the local destination and export while restoring UI state."""
    started = time.perf_counter()
    fmt = str(spec.get("format") or "").lower().lstrip(".")
    filepath = pop_destination(session_id)
    if not filepath:
        return {"success": False, "error": "No export destination was selected"}
    extension = EXTENSIONS.get(fmt)
    if extension is None or os.path.splitext(filepath)[1].lower() != extension:
        return {"success": False, "error": "Export destination extension mismatch"}
    context = bpy.context
    _telemetry_initiated(context, fmt)

    active = context.view_layer.objects.active
    selected = list(context.selected_objects)
    mode = active.mode if active else 'OBJECT'
    scene = context.scene
    animations = spec.get("animations", None)
    if animations is not None:
        animations = [str(name) for name in animations]
    counts = {}
    try:
        if active and mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        meshes = resolve_targets(
            str(spec.get("target_scope") or "scene"),
            list(spec.get("object_names") or []),
        )
        if not meshes:
            return {"success": False, "error": "No mesh objects match the export target"}
        try:
            readiness_bypassed = not run_preflight(spec).get("ready", True)
        except Exception:
            readiness_bypassed = False
        armatures = _required_armatures(meshes)
        counts = {"mesh_count": len(meshes), "armature_count": len(armatures),
                  "readiness_bypassed": readiness_bypassed}
        export_objects = set(meshes) | armatures
        if bpy.ops.object.select_all.poll():
            bpy.ops.object.select_all(action='DESELECT')
        for obj in export_objects:
            obj.select_set(True)
        context.view_layer.objects.active = meshes[0]
        staged, textures_folder = 0, ""
        with clip_selection(armatures, animations, scene) as (clips, clips_missing):
            with _temporary_export_materials(meshes):
                # OBJ: packed / generated images never reach the .mtl, so they
                # are staged beside the OBJ and referenced relatively.
                texture_ctx = (staged_obj_textures(meshes, filepath) if fmt == "obj"
                               else nullcontext((0, "")))
                with texture_ctx as (staged, textures_folder):
                    overrides = {"path_mode": "RELATIVE"} if staged else None
                    status, kwargs, anim_mode, warning = _run_operator(
                        fmt, filepath, str(spec.get("use_case") or "other"), animations,
                        overrides,
                    )
        if 'FINISHED' not in status:
            raise RuntimeError(f"Blender exporter returned {sorted(status)}")
        if fmt == "obj":
            warning = "OBJ is static-only; rigs and animation were omitted."
            clips = []
        size = 0
        try:
            size = os.path.getsize(filepath)
        except OSError:
            pass
        verification = verify_export(filepath, fmt, {
            "mesh_count": len(meshes), "armature_count": len(armatures),
            "clips": clips if animations is not None else None, "joined": False,
            "images_expected": staged if fmt == "obj" else _images_expected(meshes),
            "compression": "none",
        })
        if verification.get("checked") and verification.get("animations"):
            # Names as the FILE holds them, mapped back to the scene clip names
            # (FBX re-imports them as "<armature>|<stack>|<clip>").
            file_clips = file_clip_names(clips, verification["animations"])
            clips = file_clips if animations is None else [c for c in file_clips if c in clips] or clips
        result = {
            "success": True,
            "filepath_basename": os.path.basename(filepath),
            "format": fmt,
            "mesh_count": len(meshes),
            "armature_count": len(armatures),
            "mesh_names": [obj.name for obj in meshes][:MESH_NAME_LIMIT],
            "file_size_bytes": size,
            "warning": warning.strip(),
            "clips": clips,
            "clips_requested": animations,
            "clips_missing": clips_missing,
            "preset": preset_report(str(spec.get("use_case") or "other"), fmt, kwargs, anim_mode),
            "textures_folder": textures_folder,
            "verification": verification,
            "duration_ms": int((time.perf_counter() - started) * 1000),
        }
        _telemetry(context, fmt, spec, success=True, extension=extension, started=started, extra={
            **counts, "clip_count": len(clips),
            "verification_checked": bool(verification.get("checked")),
            "verification_passed": bool(verification.get("passed")),
            "issue_count": len(verification.get("issues") or []),
            "file_size_kb": int(size // 1024),
        })
        return result
    except Exception as exc:
        _telemetry(context, fmt, spec, success=False, extension=extension, started=started,
                   extra={**counts, "verification_checked": False,
                          "verification_passed": False, "issue_count": 0})
        return {"success": False, "error": scrub_error(exc)}
    finally:
        clear_repair_cache(session_id)
        try:
            if bpy.ops.object.select_all.poll():
                bpy.ops.object.select_all(action='DESELECT')
            for obj in selected:
                if obj.name in context.view_layer.objects:
                    obj.select_set(True)
            if active and active.name in context.view_layer.objects:
                context.view_layer.objects.active = active
                if mode != 'OBJECT':
                    bpy.ops.object.mode_set(mode=mode)
        except Exception:
            pass


def resolve_export_folder(kind: str) -> str:
    """A client-side folder for a picker-less export. Only the KIND is ever
    reported back; the path stays on this machine."""
    kind = str(kind or "downloads").lower()
    if kind == "downloads":
        home = os.path.expanduser("~")
        for name in ("Downloads", "downloads"):
            folder = os.path.join(home, name)
            if os.path.isdir(folder):
                return folder
        return os.path.join(home, "Downloads")
    if kind == "library":
        for lib in bpy.context.preferences.filepaths.asset_libraries:
            if lib.path:
                return os.path.join(bpy.path.abspath(lib.path), "exports")
    return os.path.join(bpy.app.tempdir or os.path.expanduser("~"), "mixar_exports")


def _unique_path(folder: str, stem: str, extension: str) -> str:
    candidate = os.path.join(folder, stem + extension)
    index = 2
    while os.path.exists(candidate):
        candidate = os.path.join(folder, f"{stem}_{index}{extension}")
        index += 1
    return candidate


def safe_stem(value, extension: str = "") -> str:
    stem = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(value or "export")).strip(" .")[:72] or "export"
    if extension and stem.lower().endswith(extension):
        stem = stem[: -len(extension)].strip(" .") or "export"
    return stem


def run_export_to(session_id: str, spec: dict, folder_kind: str = "downloads") -> dict:
    """Picker-less export: write ``<suggested_filename>.<ext>`` into the user's
    Downloads (or library / temp) folder, never overwriting, and report the
    basename plus the folder KIND."""
    fmt = str(spec.get("format") or "").lower().lstrip(".")
    extension = EXTENSIONS.get(fmt)
    if extension is None:
        return {"success": False, "error": f"Unsupported export format: {fmt}"}
    kind = str(folder_kind or "downloads").lower()
    if kind not in FOLDER_KINDS:
        return {"success": False, "error": f"unknown export folder kind {kind!r}"}
    folder = resolve_export_folder(kind)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError as exc:
        return {"success": False, "error": f"could not create the {kind} folder ({exc.__class__.__name__})"}
    from .export_destination import set_destination
    set_destination(session_id, _unique_path(folder, safe_stem(spec.get("suggested_filename"), extension), extension))
    spec = {**spec, "destination": kind}
    result = run_export(session_id, spec)
    if result.get("success"):
        result["folder"] = kind
    return result


def inspect_export(spec: dict) -> dict:
    """RPC entrypoint used before the native save picker is opened."""
    try:
        return run_preflight(spec)
    except Exception as exc:
        return {"success": False, "ready": False, "error": scrub_error(exc)}
