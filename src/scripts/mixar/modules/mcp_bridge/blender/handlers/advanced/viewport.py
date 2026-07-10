"""
Advanced viewport handlers for Blender MCP Bridge.
Provides viewport screenshot capture, inline graphics capture, and quick Eevee preview renders.
"""

import os
import base64
import tempfile
import bpy
from ...utils.response import ok_response, error_response
from ...utils.compat import is_blender_4, get_eevee_engine_name
from .. import register_handler


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_viewport_screenshot(params):
    """
    Capture a screenshot of the 3D viewport using OpenGL render.

    Route: POST /api/viewport/screenshot

    Required params:
        filepath (str): Absolute output path for the image file.
    Optional params:
        width  (int): Render width in pixels. Defaults to current render width.
        height (int): Render height in pixels. Defaults to current render height.
    """
    filepath = params.get("filepath")
    if not filepath:
        return error_response("filepath is required")

    scene = bpy.context.scene
    render = scene.render

    # Save current settings
    orig_filepath = render.filepath
    orig_width = render.resolution_x
    orig_height = render.resolution_y
    orig_percentage = render.resolution_percentage

    try:
        render.filepath = filepath

        if params.get("width"):
            render.resolution_x = int(params["width"])
        if params.get("height"):
            render.resolution_y = int(params["height"])
        render.resolution_percentage = 100

        # Find a 3D viewport area and override context
        viewport_area = None
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                viewport_area = area
                break

        if viewport_area is None:
            return error_response("No 3D viewport area found in current screen")

        with bpy.context.temp_override(area=viewport_area):
            bpy.ops.render.opengl(write_still=True)

        actual_width = render.resolution_x
        actual_height = render.resolution_y

        return ok_response({
            "filepath": filepath,
            "width": actual_width,
            "height": actual_height,
        })
    except Exception as e:
        return error_response(f"Viewport screenshot failed: {e}")
    finally:
        render.filepath = orig_filepath
        render.resolution_x = orig_width
        render.resolution_y = orig_height
        render.resolution_percentage = orig_percentage


def _handle_render_preview(params):
    """
    Quick Eevee preview render at reduced resolution.

    Route: POST /api/viewport/render-preview

    Required params:
        filepath (str): Absolute output path for the rendered image.
    Optional params:
        resolution_percentage (int): Render resolution percentage (1-100). Defaults to 50.
        samples (int): Number of Eevee render samples. Defaults to 16.
    """
    filepath = params.get("filepath")
    if not filepath:
        return error_response("filepath is required")

    resolution_percentage = int(params.get("resolution_percentage", 50))
    samples = int(params.get("samples", 16))

    scene = bpy.context.scene
    render = scene.render
    eevee = scene.eevee

    # Save all render settings we will modify
    orig_engine = render.engine
    orig_filepath = render.filepath
    orig_percentage = render.resolution_percentage
    orig_write_still = True  # not a property; ops handles it

    if is_blender_4():
        orig_samples = eevee.taa_render_samples
    else:
        orig_samples = eevee.taa_render_samples  # same attribute in 3.x

    try:
        # Apply preview settings
        render.engine = get_eevee_engine_name()
        render.filepath = filepath
        render.resolution_percentage = resolution_percentage
        eevee.taa_render_samples = samples

        bpy.ops.render.render(write_still=True)

        actual_width = int(render.resolution_x * render.resolution_percentage / 100)
        actual_height = int(render.resolution_y * render.resolution_percentage / 100)

        return ok_response({
            "filepath": filepath,
            "engine": render.engine,
            "resolution_percentage": resolution_percentage,
            "samples": samples,
            "width": actual_width,
            "height": actual_height,
        })
    except Exception as e:
        return error_response(f"Preview render failed: {e}")
    finally:
        render.engine = orig_engine
        render.filepath = orig_filepath
        render.resolution_percentage = orig_percentage
        eevee.taa_render_samples = orig_samples


def _handle_viewport_graphics_capture(params):
    """
    Capture the 3D viewport as an inline base64 PNG image.

    Route: POST /api/viewport/graphics-capture

    Optional params:
        width      (int):  Image width in pixels. Defaults to 512.
        height     (int):  Image height in pixels. Defaults to 512.
        use_camera (bool): Render from the active scene camera instead of
                           the viewport angle. Defaults to False.
    """
    width = int(params.get("width", 512))
    height = int(params.get("height", 512))
    use_camera = bool(params.get("use_camera", False))

    tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
    tmp_path = tmp.name
    tmp.close()

    scene = bpy.context.scene
    render = scene.render

    # Save current settings
    orig_filepath = render.filepath
    orig_width = render.resolution_x
    orig_height = render.resolution_y
    orig_percentage = render.resolution_percentage
    orig_format = render.image_settings.file_format

    try:
        render.resolution_x = width
        render.resolution_y = height
        render.resolution_percentage = 100
        render.filepath = tmp_path
        render.image_settings.file_format = 'PNG'

        # Find a 3D viewport area and override context
        viewport_area = None
        for area in bpy.context.screen.areas:
            if area.type == "VIEW_3D":
                viewport_area = area
                break

        if viewport_area is None:
            return error_response("No 3D viewport area found in current screen")

        # If use_camera is True, switch the viewport to camera view before capture
        orig_view_perspective = None
        if use_camera:
            if scene.camera is None:
                return error_response("use_camera is True but no active camera found in the scene")
            for space in viewport_area.spaces:
                if space.type == 'VIEW_3D':
                    orig_view_perspective = space.region_3d.view_perspective
                    space.region_3d.view_perspective = 'CAMERA'
                    break

        with bpy.context.temp_override(area=viewport_area):
            bpy.ops.render.opengl(write_still=True)

        with open(tmp_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")

        return ok_response({
            "base64": b64,
            "width": width,
            "height": height,
        })
    except Exception as e:
        return error_response(f"Viewport capture failed: {e}")
    finally:
        # Restore camera view perspective if we changed it
        if orig_view_perspective is not None:
            for space in viewport_area.spaces:
                if space.type == 'VIEW_3D':
                    space.region_3d.view_perspective = orig_view_perspective
                    break
        render.filepath = orig_filepath
        render.resolution_x = orig_width
        render.resolution_y = orig_height
        render.resolution_percentage = orig_percentage
        render.image_settings.file_format = orig_format
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


register_handler("viewport", "screenshot", _handle_viewport_screenshot)
register_handler("viewport", "render-preview", _handle_render_preview)
register_handler("viewport", "graphics-capture", _handle_viewport_graphics_capture)
