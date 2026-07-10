"""
Advanced render extended handlers for Blender MCP Bridge.
Provides: render/engine-set, render/execute, render/cycles-settings,
          render/eevee-settings, render/output-settings, render/color-management,
          render/compositing-setup, render/stamp-settings
"""

import bpy
from ...utils.response import ok_response, error_response, coerce_value
from ...utils.compat import is_blender_4, get_eevee_engine_name
from ...utils.context_helpers import is_valid_rna_property
from .. import register_handler


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_render_engine_set(params):
    """
    Set the active render engine for the current scene.
    Route: render/engine-set
    """
    engine = params.get("engine")
    if not engine:
        return error_response("Parameter 'engine' is required.")

    # Compatibility aliases: accept legacy short names and old enum values
    eevee_name = get_eevee_engine_name()
    ENGINE_ALIASES = {
        "EEVEE": eevee_name,
        "BLENDER_EEVEE": eevee_name,
        "BLENDER_EEVEE_NEXT": eevee_name,
        "WORKBENCH": "BLENDER_WORKBENCH",
    }
    engine = ENGINE_ALIASES.get(engine.upper(), engine.upper())

    ENGINE_MAP = {
        eevee_name:           eevee_name,
        "CYCLES":             "CYCLES",
        "BLENDER_WORKBENCH":  "BLENDER_WORKBENCH",
    }

    engine_id = ENGINE_MAP.get(engine)
    if engine_id is None:
        return error_response(
            f"Unknown engine '{engine}'. Valid values: {eevee_name}, CYCLES, BLENDER_WORKBENCH."
        )

    try:
        bpy.context.scene.render.engine = engine_id
        return ok_response({
            "engine":    engine.upper(),
            "engine_id": bpy.context.scene.render.engine,
        })
    except Exception as e:
        return error_response(f"Failed to set render engine to '{engine}': {e}")


def _handle_render_execute(params):
    """
    Execute a render of the current scene (single frame or full animation).
    Route: render/execute
    """
    filepath    = params.get("filepath")
    animation   = bool(params.get("animation", False))
    frame_start = params.get("frame_start")
    frame_end   = params.get("frame_end")

    try:
        scene = bpy.context.scene

        if filepath:
            scene.render.filepath = filepath
        if frame_start is not None:
            scene.frame_start = int(frame_start)
        if frame_end is not None:
            scene.frame_end = int(frame_end)

        if animation:
            bpy.ops.render.render(animation=True)
        else:
            bpy.ops.render.render(write_still=bool(filepath))

        return ok_response({
            "filepath":    scene.render.filepath,
            "animation":   animation,
            "frame_start": scene.frame_start,
            "frame_end":   scene.frame_end,
        })
    except Exception as e:
        return error_response(f"Render execution failed: {e}")


def _handle_render_cycles_settings(params):
    """
    Configure Cycles render settings for the current scene.
    Route: render/cycles-settings
    """
    samples = params.get("samples")
    denoise = params.get("denoise")
    device  = params.get("device")
    bounces = params.get("bounces")

    try:
        scene  = bpy.context.scene
        cycles = scene.cycles

        if samples is not None:
            cycles.samples = int(samples)
        if denoise is not None:
            cycles.use_denoising = bool(denoise)
        if device:
            device_upper = device.upper()
            if device_upper not in ("CPU", "GPU"):
                return error_response(
                    f"Invalid device '{device}'. Valid values: CPU, GPU."
                )
            cycles.device = device_upper
        if bounces is not None:
            cycles.max_bounces = int(bounces)

        return ok_response({
            "samples":     cycles.samples,
            "denoise":     cycles.use_denoising,
            "device":      cycles.device,
            "max_bounces": cycles.max_bounces,
        })
    except Exception as e:
        return error_response(f"Failed to apply Cycles settings: {e}")


def _handle_render_eevee_settings(params):
    """
    Configure EEVEE render settings for the current scene.
    Route: render/eevee-settings
    """
    samples        = params.get("samples")
    ao             = params.get("ao")
    bloom          = params.get("bloom")
    ssr            = params.get("ssr")
    shadow_quality = params.get("shadow_quality")

    try:
        scene    = bpy.context.scene
        eevee    = scene.eevee
        warnings = []

        if samples is not None:
            eevee.taa_render_samples = int(samples)

        if is_blender_4():
            # Bloom is removed in EEVEE Next (Blender 4.x)
            if bloom is not None:
                warnings.append(
                    "bloom is not available in EEVEE Next (Blender 4.x); setting was ignored."
                )

            # SSR replaced by raytracing in Blender 4.x
            if ssr is not None:
                if hasattr(eevee, "use_raytracing"):
                    eevee.use_raytracing = bool(ssr)
                else:
                    warnings.append(
                        "SSR / raytracing toggle is not available in this Blender 4.x build; setting was ignored."
                    )

            # AO: GTAO still present but attribute may differ
            if ao is not None:
                if hasattr(eevee, "use_gtao"):
                    eevee.use_gtao = bool(ao)
                else:
                    warnings.append(
                        "Ambient occlusion (use_gtao) attribute changed in this Blender 4.x build; setting was ignored."
                    )
        else:
            # Blender 3.x
            if bloom is not None:
                eevee.use_bloom = bool(bloom)
            if ssr is not None:
                eevee.use_ssr = bool(ssr)
            if ao is not None:
                eevee.use_gtao = bool(ao)

        if shadow_quality is not None:
            if hasattr(eevee, "shadow_cube_size"):
                eevee.shadow_cube_size = str(shadow_quality)
            else:
                warnings.append(
                    "shadow_cube_size attribute not found on this Blender version; shadow_quality was ignored."
                )

        result = {
            "taa_render_samples": eevee.taa_render_samples,
        }
        if hasattr(eevee, "use_gtao"):
            result["ao"] = eevee.use_gtao
        if hasattr(eevee, "use_bloom"):
            result["bloom"] = eevee.use_bloom
        if hasattr(eevee, "use_ssr"):
            result["ssr"] = eevee.use_ssr
        if hasattr(eevee, "use_raytracing"):
            result["raytracing"] = eevee.use_raytracing
        if hasattr(eevee, "shadow_cube_size"):
            result["shadow_cube_size"] = eevee.shadow_cube_size
        if warnings:
            result["warnings"] = warnings

        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to apply EEVEE settings: {e}")


def _handle_render_output_settings(params):
    """
    Configure the scene render output: resolution, format, colour depth, filepath.
    Route: render/output-settings
    """
    resolution_x = params.get("resolution_x")
    resolution_y = params.get("resolution_y")
    fmt          = params.get("format")
    color_depth  = params.get("color_depth")
    filepath     = params.get("filepath")

    if resolution_x is None:
        return error_response("Parameter 'resolution_x' is required.")
    if resolution_y is None:
        return error_response("Parameter 'resolution_y' is required.")
    if not fmt:
        return error_response("Parameter 'format' is required.")
    if not filepath:
        return error_response("Parameter 'filepath' is required.")

    try:
        render = bpy.context.scene.render

        render.resolution_x = int(resolution_x)
        render.resolution_y = int(resolution_y)
        render.image_settings.file_format = fmt.upper()

        if color_depth:
            render.image_settings.color_depth = str(color_depth)

        render.filepath = filepath

        result = {
            "resolution_x": render.resolution_x,
            "resolution_y": render.resolution_y,
            "format":       render.image_settings.file_format,
            "color_depth":  render.image_settings.color_depth,
            "filepath":     render.filepath,
        }
        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to apply output settings: {e}")


def _handle_render_color_management(params):
    """
    Configure the scene's colour management (view transform, look, exposure, gamma).
    Route: render/color-management
    """
    view_transform = params.get("view_transform")
    look           = params.get("look")
    exposure       = params.get("exposure")
    gamma          = params.get("gamma")

    TRANSFORM_MAP = {
        "STANDARD": "Standard",
        "FILMIC":   "Filmic",
        "AGXBASE":  "AgX",
        "RAW":      "Raw",
    }

    try:
        cm = bpy.context.scene.view_settings

        if view_transform:
            mapped = TRANSFORM_MAP.get(view_transform.upper(), view_transform)
            cm.view_transform = mapped
        if look is not None:
            cm.look = look
        if exposure is not None:
            cm.exposure = float(exposure)
        if gamma is not None:
            cm.gamma = float(gamma)

        return ok_response({
            "view_transform": cm.view_transform,
            "look":           cm.look,
            "exposure":       cm.exposure,
            "gamma":          cm.gamma,
        })
    except Exception as e:
        return error_response(f"Failed to apply colour management settings: {e}")


def _handle_render_compositing_setup(params):
    """
    Enable the compositor node tree and add the specified compositor nodes to it.
    Route: render/compositing-setup
    """
    nodes = params.get("nodes")
    if not isinstance(nodes, list):
        return error_response("Parameter 'nodes' must be a non-empty array.")
    if len(nodes) == 0:
        return error_response("Parameter 'nodes' must contain at least one node configuration.")

    NODE_TYPE_MAP = {
        "GLARE":              "CompositorNodeGlare",
        "COLOR_BALANCE":      "CompositorNodeColorBalance",
        "BLUR":               "CompositorNodeBlur",
        "DENOISE":            "CompositorNodeDenoise",
        "LENS_DISTORTION":    "CompositorNodeLensdist",
        "VIGNETTE":           "CompositorNodeLensdist",  # closest approximation
        "MIX":                "CompositorNodeMixRGB",
        "BRIGHTNESS_CONTRAST":"CompositorNodeBrightContrast",
    }

    try:
        scene = bpy.context.scene
        scene.use_nodes = True
        tree  = scene.node_tree

        created_nodes = []
        for node_config in nodes:
            node_type = node_config.get("type")
            if not node_type:
                return error_response(
                    "Each node configuration object must have a 'type' field."
                )

            node_name = node_config.get("name")

            # Map friendly name → Blender class name; fall back to raw value
            bl_type = NODE_TYPE_MAP.get(node_type.upper(), node_type)

            try:
                node = tree.nodes.new(bl_type)
            except Exception as node_err:
                return error_response(
                    f"Failed to create compositor node of type '{node_type}' "
                    f"(resolved to '{bl_type}'): {node_err}"
                )

            if node_name:
                node.name  = node_name
                node.label = node_name

            # Apply any extra input properties
            inputs = node_config.get("inputs", {})
            if isinstance(inputs, dict):
                for key, value in inputs.items():
                    if is_valid_rna_property(node, key):
                        try:
                            current = getattr(node, key, None)
                            if current is not None:
                                value = coerce_value(current, value)
                            setattr(node, key, value)
                        except Exception:
                            pass  # silently skip read-only or incompatible attrs

            created_nodes.append({
                "name":      node.name,
                "type":      node.bl_idname,
            })

        return ok_response({
            "use_nodes":     scene.use_nodes,
            "created_nodes": created_nodes,
            "count":         len(created_nodes),
        })
    except Exception as e:
        return error_response(f"Failed to set up compositor nodes: {e}")


def _handle_render_stamp_settings(params):
    """
    Apply render stamp (metadata burn-in) settings to the scene render.
    Route: render/stamp-settings
    """
    stamp_params = params.get("params")
    if not isinstance(stamp_params, dict):
        return error_response(
            "Parameter 'params' must be an object of render stamp key/value pairs."
        )

    try:
        render    = bpy.context.scene.render
        applied   = []
        skipped   = []

        for key, value in stamp_params.items():
            if is_valid_rna_property(render, key):
                try:
                    current = getattr(render, key, None)
                    if current is not None:
                        value = coerce_value(current, value)
                    setattr(render, key, value)
                    applied.append(key)
                except Exception as attr_err:
                    skipped.append({"key": key, "reason": str(attr_err)})
            else:
                skipped.append({"key": key, "reason": "not a valid RNA property on render"})

        result = {
            "applied": applied,
            "applied_count": len(applied),
        }
        if skipped:
            result["skipped"] = skipped

        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to apply stamp settings: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("render", "engine-set",          _handle_render_engine_set)
register_handler("render", "execute",             _handle_render_execute)
register_handler("render", "cycles-settings",     _handle_render_cycles_settings)
register_handler("render", "eevee-settings",      _handle_render_eevee_settings)
register_handler("render", "output-settings",     _handle_render_output_settings)
register_handler("render", "color-management",    _handle_render_color_management)
register_handler("render", "compositing-setup",   _handle_render_compositing_setup)
register_handler("render", "stamp-settings",      _handle_render_stamp_settings)
