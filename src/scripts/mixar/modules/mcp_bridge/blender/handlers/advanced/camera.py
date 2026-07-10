"""
Advanced camera handlers for Blender MCP Bridge.
Provides: camera/create, camera/configure, camera/look-at, camera/set-active,
          camera/orbit, camera/frame-object, camera/render-settings
"""

import math
import bpy
from mathutils import Vector, Euler
from ...utils.response import ok_response, error_response, not_found
from ...utils.context_helpers import ensure_context_for_object, temp_override
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_camera_object(name):
    """Return (obj, None) or (None, error_response) for a CAMERA object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name, "Camera")
    if obj.type != "CAMERA":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', not 'CAMERA'."
        )
    return obj, None


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_camera_create(params):
    """
    Create a new camera object in the scene.
    Route: POST /api/camera/create
    """
    try:
        name = params.get("camera_name") or params.get("name") or "Camera"
        location = params.get("location", [0.0, 0.0, 0.0])
        rotation = params.get("rotation", [0.0, 0.0, 0.0])
        focal_length = params.get("focal_length", 50.0)

        cam_data = bpy.data.cameras.new(name)
        cam_data.lens = focal_length

        obj = bpy.data.objects.new(name, cam_data)
        bpy.context.collection.objects.link(obj)

        obj.location = Vector(location)
        obj.rotation_euler = Euler(rotation, "XYZ")

        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)

        return ok_response({
            "object_name": obj.name,
            "location": list(obj.location),
            "rotation_euler": list(obj.rotation_euler),
            "focal_length": cam_data.lens,
        })
    except Exception as e:
        return error_response(f"Failed to create camera: {e}")


def _handle_camera_configure(params):
    """
    Configure an existing camera's optical properties.
    Route: POST /api/camera/configure
    """
    name = params.get("camera_name") or params.get("name")
    if not name:
        return error_response("Parameter 'camera_name' (or 'name') is required.")

    obj, err = _get_camera_object(name)
    if err:
        return err

    try:
        cam = obj.data

        focal_length = params.get("focal_length")
        if focal_length is not None:
            cam.lens = focal_length

        sensor_size = params.get("sensor_size")
        if sensor_size is not None:
            cam.sensor_width = sensor_size

        clip_start = params.get("clip_start")
        if clip_start is not None:
            cam.clip_start = clip_start

        clip_end = params.get("clip_end")
        if clip_end is not None:
            cam.clip_end = clip_end

        dof = params.get("dof")
        if dof is not None:
            cam.dof.use_dof = True
            focus_distance = dof.get("focus_distance")
            if focus_distance is not None:
                cam.dof.focus_distance = focus_distance
            aperture_fstop = dof.get("aperture_fstop")
            if aperture_fstop is not None:
                cam.dof.aperture_fstop = aperture_fstop

        return ok_response({
            "object_name": obj.name,
            "focal_length": cam.lens,
            "sensor_width": cam.sensor_width,
            "clip_start": cam.clip_start,
            "clip_end": cam.clip_end,
            "dof_enabled": cam.dof.use_dof,
            "dof_focus_distance": cam.dof.focus_distance if cam.dof.use_dof else None,
            "dof_aperture_fstop": cam.dof.aperture_fstop if cam.dof.use_dof else None,
        })
    except Exception as e:
        return error_response(f"Failed to configure camera '{name}': {e}")


def _handle_camera_look_at(params):
    """
    Orient a camera to face a target object or world-space point.
    Route: POST /api/camera/look-at
    """
    camera_name = params.get("camera_name") or params.get("name")
    if not camera_name:
        return error_response("Parameter 'camera_name' (or 'name') is required.")

    obj, err = _get_camera_object(camera_name)
    if err:
        return err

    target_raw = params.get("target")
    target_point = params.get("target_point")

    # If the caller passed target as a list/tuple (i.e. a coordinate), treat it
    # as target_point so we produce a clear error rather than crashing inside
    # bpy_prop_collection (which cannot accept non-string keys).
    if isinstance(target_raw, (list, tuple)):
        if target_point is not None:
            return error_response("Cannot specify both 'target' and 'target_point'")
        target_point = target_raw
        target_raw = None

    target_name = target_raw  # guaranteed to be str or None from here on

    if target_name is not None and target_point is not None:
        return error_response("Cannot specify both 'target' and 'target_point'")

    if target_name is None and target_point is None:
        return error_response(
            "Either 'target' (object name) or 'target_point' ([x, y, z]) must be provided."
        )

    # Reject empty string early — bpy.data.objects.get("") returns None,
    # which would produce a misleading not_found("") error.
    if target_name is not None and target_name == "":
        return error_response("target name cannot be empty")

    # Validate types before touching bpy collections
    if target_name is not None and not isinstance(target_name, str):
        return error_response(
            f"'target' must be an object name string, got {type(target_name).__name__}."
        )
    if target_point is not None and (
        not isinstance(target_point, (list, tuple)) or len(target_point) != 3
    ):
        return error_response("'target_point' must be a list of exactly 3 numbers [x, y, z].")
    if target_point is not None and not all(
        isinstance(v, (int, float)) and not isinstance(v, bool)
        for v in target_point
    ):
        return error_response(
            "'target_point' elements must all be numbers (int or float), "
            f"got: {[type(v).__name__ for v in target_point]}."
        )

    try:
        if target_name is not None:
            target_obj = bpy.data.objects.get(target_name)
            if target_obj is None:
                return not_found(target_name, "Target object")
            target_pos = target_obj.location.copy()
        else:
            target_pos = Vector(target_point)

        direction = target_pos - obj.location
        if direction.length == 0.0:
            return error_response(
                "Camera location and target position are identical; cannot compute direction."
            )

        obj.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()

        return ok_response({
            "camera_name": obj.name,
            "target": target_name if target_name else target_point,
            "rotation_euler": [round(v, 6) for v in obj.rotation_euler],
        })
    except Exception as e:
        return error_response(f"camera/look-at failed: {e}")


def _handle_camera_set_active(params):
    """
    Set a camera object as the active scene camera.
    Route: POST /api/camera/set-active
    """
    name = params.get("camera_name") or params.get("name")
    if not name:
        return error_response("Parameter 'camera_name' (or 'name') is required.")

    obj, err = _get_camera_object(name)
    if err:
        return err

    try:
        bpy.context.scene.camera = obj
        return ok_response({
            "active_camera": obj.name,
        })
    except Exception as e:
        return error_response(f"Failed to set active camera: {e}")


def _handle_camera_orbit(params):
    """
    Create an orbit animation — camera circles target object.
    Route: POST /api/camera/orbit
    """
    target_name = params.get("target")
    if not target_name:
        return error_response("Parameter 'target' (object name) is required.")

    target_obj = bpy.data.objects.get(target_name)
    if target_obj is None:
        return not_found(target_name, "Target object")

    radius = params.get("radius", 5.0)
    height = params.get("height", 2.0)
    frames = params.get("frames", 120)

    try:
        scene = bpy.context.scene

        # Create an Empty at the target's world location
        empty_name = f"{target_name}_OrbitPivot"
        empty = bpy.data.objects.new(empty_name, None)
        empty.empty_display_type = "PLAIN_AXES"
        empty.location = target_obj.location.copy()
        bpy.context.collection.objects.link(empty)

        # Create or reuse a camera
        cam_name = f"{target_name}_OrbitCam"
        cam_obj = bpy.data.objects.get(cam_name)
        if cam_obj is None or cam_obj.type != "CAMERA":
            cam_data = bpy.data.cameras.new(cam_name)
            cam_obj = bpy.data.objects.new(cam_name, cam_data)
            bpy.context.collection.objects.link(cam_obj)

        # Position camera relative to empty (offset along Y by radius, raise Z)
        cam_obj.location = Vector((0.0, -radius, height))
        cam_obj.rotation_euler = Euler(
            (math.atan2(height, radius), 0.0, 0.0), "XYZ"
        )

        # Parent camera to empty without offset
        cam_obj.parent = empty
        cam_obj.matrix_parent_inverse = empty.matrix_world.inverted()

        # Keyframe Empty Z rotation: 0 at frame 1, 2*pi at frame (frames)
        empty.rotation_euler = Euler((0.0, 0.0, 0.0), "XYZ")
        empty.keyframe_insert(data_path="rotation_euler", frame=1)

        empty.rotation_euler = Euler((0.0, 0.0, math.pi * 2), "XYZ")
        empty.keyframe_insert(data_path="rotation_euler", frame=frames)

        # Set interpolation to LINEAR for smooth constant-speed orbit
        if empty.animation_data and empty.animation_data.action:
            for fcurve in empty.animation_data.action.fcurves:
                for kp in fcurve.keyframe_points:
                    kp.interpolation = "LINEAR"

        scene.frame_end = max(scene.frame_end, frames)

        return ok_response({
            "camera_name": cam_obj.name,
            "pivot_empty": empty.name,
            "target": target_name,
            "radius": radius,
            "height": height,
            "frames": frames,
        })
    except Exception as e:
        return error_response(f"camera/orbit failed: {e}")


def _handle_camera_frame_object(params):
    """
    Reposition the active camera to frame the specified object.
    Route: POST /api/camera/frame-object
    """
    object_name = params.get("object_name")
    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return not_found(object_name)

    margin = params.get("margin", 1.2)  # object_name is generic here — default entity type is fine

    scene = bpy.context.scene
    if scene.camera is None:
        return error_response("No active scene camera. Use blender_camera_set_active first.")

    cam_obj = scene.camera

    try:
        # Deselect all, select target object
        bpy.ops.object.select_all(action="DESELECT")
        obj.select_set(True)
        bpy.context.view_layer.objects.active = obj

        # Try using the VIEW_3D operator
        framed_via_operator = False
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                for region in area.regions:
                    if region.type == "WINDOW":
                        for space in area.spaces:
                            if space.type == "VIEW_3D":
                                with bpy.context.temp_override(
                                    area=area, region=region, space_data=space
                                ):
                                    try:
                                        bpy.ops.view3d.camera_to_view_selected()
                                        framed_via_operator = True
                                    except (RuntimeError, Exception):
                                        pass
                        break
                break

        if not framed_via_operator:
            # Fallback: manual bounding-box calculation
            bbox_corners = [obj.matrix_world @ Vector(corner) for corner in obj.bound_box]
            center = sum(bbox_corners, Vector()) / 8.0
            max_extent = max(
                max(abs(c.x - center.x) for c in bbox_corners),
                max(abs(c.y - center.y) for c in bbox_corners),
                max(abs(c.z - center.z) for c in bbox_corners),
            )
            fov = cam_obj.data.angle  # radians
            distance = (max_extent * margin) / math.tan(fov / 2.0)
            direction = (cam_obj.location - center)
            if direction.length > 0:
                direction = direction.normalized()
            else:
                direction = Vector((0.0, -1.0, 0.5)).normalized()
            cam_obj.location = center + direction * distance
            look_dir = center - cam_obj.location
            cam_obj.rotation_euler = look_dir.to_track_quat("-Z", "Y").to_euler()

        return ok_response({
            "camera_name": cam_obj.name,
            "framed_object": obj.name,
            "margin": margin,
            "method": "operator" if framed_via_operator else "bounding_box_fallback",
            "camera_location": [round(v, 6) for v in cam_obj.location],
        })
    except Exception as e:
        return error_response(f"camera/frame-object failed: {e}")


def _handle_camera_render_settings(params):
    """
    Configure global render output settings.
    Route: POST /api/camera/render-settings
    """
    try:
        render = bpy.context.scene.render

        resolution_x = params.get("resolution_x")
        if resolution_x is not None:
            render.resolution_x = int(resolution_x)

        resolution_y = params.get("resolution_y")
        if resolution_y is not None:
            render.resolution_y = int(resolution_y)

        fmt = params.get("format")
        if fmt is not None:
            valid_formats = ("PNG", "JPEG", "EXR")
            fmt_upper = fmt.upper()
            if fmt_upper not in valid_formats:
                return error_response(
                    f"Unknown format '{fmt}'. Valid: {', '.join(valid_formats)}."
                )
            # Blender uses OPEN_EXR internally
            render.image_settings.file_format = (
                "OPEN_EXR" if fmt_upper == "EXR" else fmt_upper
            )

        filepath = params.get("filepath")
        if filepath is not None:
            render.filepath = filepath

        return ok_response({
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "file_format": render.image_settings.file_format,
            "filepath": render.filepath,
        })
    except Exception as e:
        return error_response(f"Failed to apply render settings: {e}")


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("camera", "create", _handle_camera_create)
register_handler("camera", "configure", _handle_camera_configure)
register_handler("camera", "look-at", _handle_camera_look_at)
register_handler("camera", "set-active", _handle_camera_set_active)
register_handler("camera", "orbit", _handle_camera_orbit)
register_handler("camera", "frame-object", _handle_camera_frame_object)
register_handler("camera", "render-settings", _handle_camera_render_settings)
