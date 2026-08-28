# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Parts-colour multi-view captures for the assembly build/refine loops.

Renders the routed scene from a fixed viewpoint catalog (paper Sec. 3.3-3.4:
orthographic faces, isometric corners, eye-level diagonals, front tilts).
"parts" shading renders Workbench with per-OBJECT colors — each committed
part carries a distinct color assigned by the compiler, so the model can see
where its part attached. "material" shading renders EEVEE for the materials
critic. Window-independent (same proven path as the platform's
render_multiview verification script), with save/restore of every touched
setting.
"""

from __future__ import annotations

import base64
import math
import tempfile
import time

import bpy
from mathutils import Vector

# name -> (azimuth_deg, elevation_deg, orthographic). Azimuth 0 sits on -Y
# looking toward +Y = the FRONT of the build (Mixar front convention is -Y).
VIEW_CATALOG = {
    "front": (0.0, 0.0, True),
    "back": (180.0, 0.0, True),
    "right": (90.0, 0.0, True),
    "left": (270.0, 0.0, True),
    "top": (0.0, 89.0, True),
    "bottom": (0.0, -89.0, True),
    "iso_fl": (315.0, 35.264, False),
    "iso_fr": (45.0, 35.264, False),
    "iso_bl": (225.0, 35.264, False),
    "iso_br": (135.0, 35.264, False),
    "iso_low_fl": (315.0, -30.0, False),
    "iso_low_br": (135.0, -30.0, False),
    "eye_fl": (315.0, 10.0, False),
    "eye_fr": (45.0, 10.0, False),
    "tilt_front_15": (0.0, 15.0, False),
    "tilt_front_30": (0.0, 30.0, False),
}

DEFAULT_BUILD_VIEWS = ["front", "right", "top", "iso_fr"]
MAX_VIEWS = 12


def _tmp_join(name: str) -> str:
    return tempfile.gettempdir().rstrip("/\\") + "/" + name


def _file_bytes(path: str) -> bytes | None:
    try:
        with open(path, "rb") as f:
            data = f.read()
        return data if len(data) >= 512 else None
    except OSError:
        return None


def _operator_capture(scene, width: int, height: int) -> str | None:
    """Fallback when ``bpy.ops.render.render`` no-ops (GUI main thread):
    the addon's render_scene operator GL-draws THIS scene through its camera.
    Viewport-shaded (parts colours may degrade) but never blank."""
    key = "asm_%d" % int(time.time() * 1000000)
    sid = getattr(scene, "mixie_session_id", "") or (
        scene.get("mixie_session_id") or ""
    )
    try:
        bpy.ops.mixie_chat.render_scene(
            scene_session=sid, scene_name=scene.name,
            width=width, height=height, job_key=key,
        )
    except Exception:  # noqa: BLE001
        return None
    res = (bpy.app.driver_namespace.get("mixie_scene_render") or {}).pop(key, None)
    if res and res.get("status") == "done":
        return res.get("image_base64")
    return None


def _pick_engine(material: bool) -> str:
    if not material:
        return "BLENDER_WORKBENCH"
    try:
        avail = bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items.keys()
    except Exception:  # noqa: BLE001
        avail = []
    for cand in ("BLENDER_EEVEE_NEXT", "BLENDER_EEVEE"):
        if cand in avail:
            return cand
    return "BLENDER_WORKBENCH"


def render_assembly_views(params: dict) -> dict:
    """params: views (names from VIEW_CATALOG), width, height,
    shading ("parts" | "material"), object_name (frame only that assembly's
    tagged objects when present)."""
    width = max(128, min(int(params.get("width") or 512), 1024))
    height = max(128, min(int(params.get("height") or 384), 1024))
    shading = str(params.get("shading") or "parts")
    object_name = params.get("object_name") or ""
    names = [v for v in (params.get("views") or DEFAULT_BUILD_VIEWS)
             if v in VIEW_CATALOG][:MAX_VIEWS]
    if not names:
        return {"success": False, "error": "no valid views requested"}

    scene = bpy.context.scene
    scene_sid = getattr(scene, "mixie_session_id", "") or (
        scene.get("mixie_session_id") or ""
    )
    content = [
        o for o in scene.objects
        if o.type == "MESH" and o.visible_get()
        and (not object_name or o.get("mixar_asm") == object_name)
    ]
    if not content:
        content = [o for o in scene.objects if o.type == "MESH" and o.visible_get()]
    if not content:
        return {"success": False, "error": "nothing to render",
                "scene_session": scene_sid}

    pts = [o.matrix_world @ Vector(c) for o in content for c in o.bound_box]
    center = Vector((
        (min(p.x for p in pts) + max(p.x for p in pts)) / 2,
        (min(p.y for p in pts) + max(p.y for p in pts)) / 2,
        (min(p.z for p in pts) + max(p.z for p in pts)) / 2,
    ))
    radius = max((p - center).length for p in pts) or 1.0

    saved = {
        "engine": scene.render.engine,
        "rx": scene.render.resolution_x, "ry": scene.render.resolution_y,
        "rp": scene.render.resolution_percentage,
        "fp": scene.render.filepath,
        "ff": scene.render.image_settings.file_format,
        "fq": scene.render.image_settings.quality,
        "camera": scene.camera,
        "world": scene.world,
    }
    temp_cam = None
    temp_world = None
    views = []
    failed = []
    methods = []
    try:
        engine = _pick_engine(shading == "material")
        scene.render.engine = engine
        if engine == "BLENDER_WORKBENCH":
            disp = scene.display
            saved["shading_color"] = disp.shading.color_type
            saved["shading_light"] = disp.shading.light
            saved["aa"] = disp.render_aa
            disp.shading.color_type = "OBJECT" if shading == "parts" else "MATERIAL"
            disp.shading.light = "STUDIO"
            disp.render_aa = "5"
        else:
            w = bpy.data.worlds.new("_asm_world")
            w.use_nodes = True
            bg = w.node_tree.nodes.get("Background")
            if bg is not None:
                bg.inputs[0].default_value = (1.0, 1.0, 1.0, 1.0)
                bg.inputs[1].default_value = 1.2
            temp_world = w
            scene.world = w
            try:
                saved["taa"] = scene.eevee.taa_render_samples
                scene.eevee.taa_render_samples = 8
            except Exception:  # noqa: BLE001
                pass
        scene.render.image_settings.file_format = "JPEG"
        scene.render.image_settings.quality = 85
        scene.render.resolution_x = width
        scene.render.resolution_y = height
        scene.render.resolution_percentage = 100

        cam_data = bpy.data.cameras.new("_asm_cam")
        temp_cam = bpy.data.objects.new("_asm_cam", cam_data)
        scene.collection.objects.link(temp_cam)
        scene.camera = temp_cam
        fov = cam_data.angle or math.radians(50)
        dist = (radius / max(math.sin(fov / 2.0), 1e-3)) * 1.25
        cam_data.clip_start = max(0.01, (dist - radius) * 0.4)
        cam_data.clip_end = dist + radius * 3.0 + 100.0

        for label in names:
            az_deg, elev_deg, ortho = VIEW_CATALOG[label]
            az, elev = math.radians(az_deg), math.radians(elev_deg)
            d = Vector((
                math.cos(elev) * math.sin(az),
                -math.cos(elev) * math.cos(az),
                math.sin(elev),
            ))
            temp_cam.location = center + d * dist
            forward = (center - temp_cam.location).normalized()
            temp_cam.rotation_euler = forward.to_track_quat("-Z", "Y").to_euler()
            if ortho:
                cam_data.type = "ORTHO"
                cam_data.ortho_scale = 2.0 * radius * 1.1
            else:
                cam_data.type = "PERSP"
            bpy.context.view_layer.update()

            base = _tmp_join(f"mixar_asm_{int(time.time() * 1000)}_{label}")
            scene.render.filepath = base
            try:
                bpy.ops.render.render(write_still=True)
            except Exception:  # noqa: BLE001
                pass
            data = _file_bytes(base + ".jpg")
            if data:
                views.append({
                    "label": label,
                    "image_base64": base64.b64encode(data).decode("ascii"),
                })
                methods.append(f"{label}:render")
            else:
                b64 = _operator_capture(scene, width, height)
                if b64:
                    views.append({"label": label, "image_base64": b64})
                    methods.append(f"{label}:operator")
                else:
                    failed.append(label)
                    methods.append(f"{label}:FAILED")

        if not views:
            return {"success": False,
                    "error": f"no views rendered (failed: {failed})",
                    "scene_session": scene_sid}
        return {
            "success": True, "views": views, "failed_views": failed,
            "view_methods": methods,
            # operator-path frames are PNG; the backend re-encodes for the
            # model anyway, so report the conservative mime when mixed.
            "image_mime": ("image/jpeg"
                           if all(m.endswith(":render") for m in methods)
                           else "image/png"),
            "width": width, "height": height,
            "engine": engine, "shading": shading, "scene_session": scene_sid,
            "objects": [o.name for o in content][:60],
        }
    finally:
        try:
            scene.render.engine = saved["engine"]
            scene.render.resolution_x = saved["rx"]
            scene.render.resolution_y = saved["ry"]
            scene.render.resolution_percentage = saved["rp"]
            scene.render.filepath = saved["fp"]
            scene.render.image_settings.file_format = saved["ff"]
            scene.render.image_settings.quality = saved["fq"]
        except Exception:  # noqa: BLE001
            pass
        try:
            if "shading_color" in saved:
                scene.display.shading.color_type = saved["shading_color"]
                scene.display.shading.light = saved["shading_light"]
                scene.display.render_aa = saved["aa"]
            if "taa" in saved:
                scene.eevee.taa_render_samples = saved["taa"]
        except Exception:  # noqa: BLE001
            pass
        if temp_cam is not None:
            try:
                scene.camera = saved["camera"]
                bpy.data.objects.remove(temp_cam, do_unlink=True)
            except Exception:  # noqa: BLE001
                pass
        if temp_world is not None:
            try:
                scene.world = saved["world"]
                bpy.data.worlds.remove(temp_world)
            except Exception:  # noqa: BLE001
                pass
        try:
            bpy.ops.mixie_chat.prune_render_cache()
        except Exception:  # noqa: BLE001
            pass
