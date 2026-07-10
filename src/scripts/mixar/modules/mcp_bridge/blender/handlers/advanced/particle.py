"""
Advanced particle handlers for Blender MCP Bridge.
Provides: particle/create, particle/configure, particle/hair-length,
          particle/hair-density, particle/emitter-physics,
          particle/instance-object, particle/weight-paint, particle/remove
"""

import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.compat import is_blender_4
from ...utils.context_helpers import ensure_context_for_object
from .. import register_handler


# ─── Helpers ───────────────────────────────────────────────────────────────────

def _get_object(object_name):
    """Return (obj, None) or (None, error_response) for any object lookup."""
    obj = bpy.data.objects.get(object_name)
    if obj is None:
        return None, not_found(object_name)
    return obj, None


def _get_particle_system(obj, system_name):
    """Return (particle_system, None) or (None, error_response)."""
    ps = obj.particle_systems.get(system_name)
    if ps is None:
        return None, error_response(
            f"Particle system '{system_name}' not found on object '{obj.name}'. "
            f"Available: {[s.name for s in obj.particle_systems]}"
        )
    return ps, None


def _blender4_warning():
    """Return the standard Blender 4.x deprecation warning string, or empty string."""
    if is_blender_4():
        return (
            "Note: Legacy particle systems are deprecated in Blender 4.x. "
            "Consider using Geometry Nodes for hair."
        )
    return ""


# ─── Handlers ──────────────────────────────────────────────────────────────────

def _handle_particle_create(params):
    """
    Add a new particle system to an object.
    Route: POST /api/particle/create
    """
    object_name = params.get("object_name")
    particle_type = params.get("type", "EMITTER").upper()
    name = params.get("name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if particle_type not in ("EMITTER", "HAIR"):
        return error_response(
            f"Invalid type '{particle_type}'. Must be 'EMITTER' or 'HAIR'."
        )

    obj, err = _get_object(object_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)
        bpy.ops.object.particle_system_add()

        ps = obj.particle_systems[-1]  # newly added system

        if name:
            ps.name = name
            ps.settings.name = name

        ps.settings.type = particle_type

        warning = _blender4_warning()

        result = {
            "object_name": obj.name,
            "system_name": ps.name,
            "system_index": len(obj.particle_systems) - 1,
            "type": particle_type,
        }
        if warning:
            result["warning"] = warning

        return ok_response(result)

    except Exception as e:
        return error_response(f"Failed to create particle system: {e}")


def _handle_particle_configure(params):
    """
    Apply a dict of settings to an existing particle system.
    Route: POST /api/particle/configure
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    config = params.get("params") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")
    if not isinstance(config, dict):
        return error_response("Parameter 'params' must be a JSON object (dict).")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    # Allowed setting keys and their expected Python types for basic validation
    _allowed_keys = {
        "count": int,
        "frame_start": float,
        "frame_end": float,
        "lifetime": float,
        "emit_from": str,
        "physics_type": str,
        "render_type": str,
    }

    try:
        settings = ps.settings
        applied = {}

        for key, value in config.items():
            if key not in _allowed_keys:
                # Skip unknown keys gracefully
                continue
            try:
                current = getattr(settings, key, None)
                if current is not None:
                    value = coerce_value(current, value)
                setattr(settings, key, value)
                applied[key] = value
            except Exception as attr_err:
                # Non-fatal: record failure but continue
                applied[f"{key}_error"] = str(attr_err)

        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "applied": applied,
        })

    except Exception as e:
        return error_response(f"Failed to configure particle system '{system_name}': {e}")


def _handle_particle_hair_length(params):
    """
    Set the hair strand length on a HAIR particle system.
    Route: POST /api/particle/hair-length
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    length = params.get("length")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")
    if length is None:
        return error_response("Parameter 'length' is required.")

    try:
        length = float(length)
    except (TypeError, ValueError):
        return error_response(f"Parameter 'length' must be a number, got: {length!r}")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    try:
        ps.settings.hair_length = length
        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "hair_length": ps.settings.hair_length,
        })
    except Exception as e:
        return error_response(f"Failed to set hair length on '{system_name}': {e}")


def _handle_particle_hair_density(params):
    """
    Set the strand count (density) on a HAIR particle system.
    Route: POST /api/particle/hair-density
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    count = params.get("count")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")
    if count is None:
        return error_response("Parameter 'count' is required.")

    try:
        count = int(count)
        if count < 1:
            raise ValueError("count must be >= 1")
    except (TypeError, ValueError) as ve:
        return error_response(f"Parameter 'count' must be a positive integer: {ve}")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    try:
        ps.settings.count = count
        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "count": ps.settings.count,
        })
    except Exception as e:
        return error_response(f"Failed to set hair density on '{system_name}': {e}")


def _handle_particle_emitter_physics(params):
    """
    Adjust physics parameters on an EMITTER particle system.
    Route: POST /api/particle/emitter-physics
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    gravity = params.get("gravity")
    velocity = params.get("velocity")
    lifetime = params.get("lifetime")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    try:
        settings = ps.settings
        applied = {}

        if gravity is not None:
            gravity = float(gravity)
            settings.effector_weights.gravity = gravity
            applied["gravity"] = gravity

        if velocity is not None:
            velocity = float(velocity)
            settings.normal_factor = velocity
            applied["velocity"] = velocity

        if lifetime is not None:
            lifetime = float(lifetime)
            if lifetime < 1:
                return error_response("Parameter 'lifetime' must be >= 1.")
            settings.lifetime = lifetime
            applied["lifetime"] = lifetime

        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "applied": applied,
        })

    except Exception as e:
        return error_response(
            f"Failed to set emitter physics on '{system_name}': {e}"
        )


def _handle_particle_instance_object(params):
    """
    Assign an instance object to a particle system (render_type = OBJECT).
    Route: POST /api/particle/instance-object
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    instance_object_name = params.get("instance_object")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")
    if not instance_object_name:
        return error_response("Parameter 'instance_object' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    instance_obj = bpy.data.objects.get(instance_object_name)
    if instance_obj is None:
        return not_found(instance_object_name)

    try:
        settings = ps.settings
        settings.render_type = "OBJECT"
        settings.instance_object = instance_obj

        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "render_type": "OBJECT",
            "instance_object": instance_obj.name,
        })

    except Exception as e:
        return error_response(
            f"Failed to set instance object on '{system_name}': {e}"
        )


def _handle_particle_weight_paint(params):
    """
    Bind a vertex group to the density channel of a particle system.
    Route: POST /api/particle/weight-paint
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")
    vertex_group = params.get("vertex_group")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")
    if vertex_group is None:
        return error_response("Parameter 'vertex_group' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    # Validate that the vertex group exists (unless clearing with empty string)
    if vertex_group and vertex_group not in obj.vertex_groups:
        available = [vg.name for vg in obj.vertex_groups]
        return error_response(
            f"Vertex group '{vertex_group}' not found on object '{obj.name}'. "
            f"Available: {available}"
        )

    try:
        ps.vertex_group_density = vertex_group
        return ok_response({
            "object_name": obj.name,
            "system_name": ps.name,
            "vertex_group_density": ps.vertex_group_density,
        })

    except Exception as e:
        return error_response(
            f"Failed to set vertex group density on '{system_name}': {e}"
        )


def _handle_particle_remove(params):
    """
    Remove a particle system slot from an object.
    Route: POST /api/particle/remove
    """
    object_name = params.get("object_name")
    system_name = params.get("system_name")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not system_name:
        return error_response("Parameter 'system_name' is required.")

    obj, err = _get_object(object_name)
    if err:
        return err

    ps, err = _get_particle_system(obj, system_name)
    if err:
        return err

    try:
        ensure_context_for_object(obj)

        # Find and activate the target system by index
        systems_list = list(obj.particle_systems)
        idx = next(
            (i for i, s in enumerate(systems_list) if s.name == system_name), None
        )
        if idx is None:
            return error_response(
                f"Could not locate index for particle system '{system_name}'."
            )

        obj.particle_systems.active_index = idx
        bpy.ops.object.particle_system_remove()

        return ok_response({
            "object_name": obj.name,
            "removed_system": system_name,
            "remaining_systems": [s.name for s in obj.particle_systems],
        })

    except Exception as e:
        return error_response(
            f"Failed to remove particle system '{system_name}' from '{object_name}': {e}"
        )


# ─── Register routes ────────────────────────────────────────────────────────────

register_handler("particle", "create",          _handle_particle_create)
register_handler("particle", "configure",       _handle_particle_configure)
register_handler("particle", "hair-length",     _handle_particle_hair_length)
register_handler("particle", "hair-density",    _handle_particle_hair_density)
register_handler("particle", "emitter-physics", _handle_particle_emitter_physics)
register_handler("particle", "instance-object", _handle_particle_instance_object)
register_handler("particle", "weight-paint",    _handle_particle_weight_paint)
register_handler("particle", "remove",          _handle_particle_remove)
