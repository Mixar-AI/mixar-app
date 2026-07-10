"""
Advanced physics handlers for Blender MCP Bridge.
Provides: physics/cloth-add, physics/cloth-configure, physics/cloth-pin,
          physics/rigid-body-add, physics/rigid-body-configure,
          physics/soft-body-add, physics/collision-add, physics/fluid-add,
          physics/bake, physics/free-bake
"""

import bpy
from ...utils.response import ok_response, error_response, not_found, coerce_value
from ...utils.context_helpers import ensure_context_for_object, temp_override
from .. import register_handler


# ─── Constants ──────────────────────────────────────────────────────────────────

CLOTH_PRESETS = {
    "COTTON": {
        "quality": 5,
        "mass": 0.3,
        "tension_stiffness": 15,
        "compression_stiffness": 15,
        "bending_stiffness": 0.5,
    },
    "SILK": {
        "quality": 5,
        "mass": 0.15,
        "tension_stiffness": 5,
        "compression_stiffness": 5,
        "bending_stiffness": 0.05,
    },
    "LEATHER": {
        "quality": 15,
        "mass": 0.4,
        "tension_stiffness": 80,
        "compression_stiffness": 80,
        "bending_stiffness": 150,
    },
    "DENIM": {
        "quality": 12,
        "mass": 0.3,
        "tension_stiffness": 40,
        "compression_stiffness": 40,
        "bending_stiffness": 10,
    },
    "RUBBER": {
        "quality": 7,
        "mass": 3.0,
        "tension_stiffness": 15,
        "compression_stiffness": 15,
        "bending_stiffness": 25,
    },
}

# Cloth settings keys that map directly to ClothSettings attributes
CLOTH_CONFIGURABLE_KEYS = {
    "mass",
    "tension_stiffness",
    "compression_stiffness",
    "bending_stiffness",
    "quality",
    "air_damping",
    "velocity_max",
}

# Soft body settings keys
SOFTBODY_CONFIGURABLE_KEYS = {
    "mass",
    "goal_stiffness",
    "goal_damping",
    "pull",
    "push",
    "damping",
    "bend",
}


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _get_object(name):
    """Return (obj, None) or (None, error_response) for any object."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    return obj, None


def _get_mesh_object(name):
    """Return (obj, None) or (None, error_response) — enforces MESH type."""
    obj = bpy.data.objects.get(name)
    if obj is None:
        return None, not_found(name)
    if obj.type != "MESH":
        return None, error_response(
            f"Object '{name}' is of type '{obj.type}', expected 'MESH'."
        )
    return obj, None


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_cloth_add(params):
    """
    Add a Cloth modifier to a mesh object, optionally applying a material preset.
    Route: POST /api/physics/cloth-add
    """
    object_name = params.get("object_name")
    preset = params.get("preset")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if preset and preset.upper() not in CLOTH_PRESETS:
        return error_response(
            f"Unknown preset '{preset}'. Valid: {', '.join(CLOTH_PRESETS.keys())}."
        )

    try:
        ensure_context_for_object(obj)

        # Check if Cloth modifier already exists
        existing = obj.modifiers.get("Cloth")
        if existing:
            return error_response(
                f"Object '{object_name}' already has a Cloth modifier. "
                "Use physics/cloth-configure to update settings."
            )

        with temp_override("VIEW_3D"):
            bpy.ops.object.modifier_add(type="CLOTH")

        cloth_mod = obj.modifiers.get("Cloth")
        if cloth_mod is None:
            return error_response("Failed to add Cloth modifier.")

        settings = cloth_mod.settings
        applied_preset = None

        if preset:
            preset_upper = preset.upper()
            p = CLOTH_PRESETS[preset_upper]
            settings.quality = p["quality"]
            settings.mass = p["mass"]
            settings.tension_stiffness = p["tension_stiffness"]
            settings.compression_stiffness = p["compression_stiffness"]
            settings.bending_stiffness = p["bending_stiffness"]
            applied_preset = preset_upper

        return ok_response({
            "object_name": obj.name,
            "modifier": "Cloth",
            "preset": applied_preset,
            "settings": {
                "quality": settings.quality,
                "mass": settings.mass,
                "tension_stiffness": settings.tension_stiffness,
                "compression_stiffness": settings.compression_stiffness,
                "bending_stiffness": settings.bending_stiffness,
            },
        })

    except Exception as e:
        return error_response(f"Failed to add Cloth modifier to '{object_name}': {e}")


def _handle_cloth_configure(params):
    """
    Configure an existing Cloth modifier's settings on a mesh object.
    Route: POST /api/physics/cloth-configure
    """
    object_name = params.get("object_name")
    cloth_params = params.get("params") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not cloth_params:
        return error_response("Parameter 'params' must be a non-empty object.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    cloth_mod = obj.modifiers.get("Cloth")
    if cloth_mod is None:
        return error_response(
            f"Object '{object_name}' has no Cloth modifier. "
            "Use physics/cloth-add first."
        )

    try:
        settings = cloth_mod.settings
        applied = {}
        skipped = {}

        for key, value in cloth_params.items():
            if key in CLOTH_CONFIGURABLE_KEYS:
                if hasattr(settings, key):
                    current = getattr(settings, key)
                    setattr(settings, key, coerce_value(current, value))
                    applied[key] = value
                else:
                    skipped[key] = f"attribute '{key}' not found on ClothSettings"
            else:
                skipped[key] = "unsupported key"

        return ok_response({
            "object_name": obj.name,
            "applied": applied,
            "skipped": skipped,
        })

    except Exception as e:
        return error_response(f"Failed to configure Cloth on '{object_name}': {e}")


def _handle_cloth_pin(params):
    """
    Assign a vertex group as the cloth pin group.
    Route: POST /api/physics/cloth-pin
    """
    object_name = params.get("object_name")
    vertex_group = params.get("vertex_group")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not vertex_group:
        return error_response("Parameter 'vertex_group' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    cloth_mod = obj.modifiers.get("Cloth")
    if cloth_mod is None:
        return error_response(
            f"Object '{object_name}' has no Cloth modifier. "
            "Use physics/cloth-add first."
        )

    if vertex_group not in obj.vertex_groups:
        return error_response(
            f"Vertex group '{vertex_group}' does not exist on '{object_name}'. "
            f"Available groups: {[g.name for g in obj.vertex_groups]}"
        )

    try:
        cloth_mod.settings.vertex_group_mass = vertex_group

        return ok_response({
            "object_name": obj.name,
            "pin_vertex_group": vertex_group,
        })

    except Exception as e:
        return error_response(f"Failed to set cloth pin group on '{object_name}': {e}")


def _handle_rigid_body_add(params):
    """
    Add a Rigid Body to an object.
    Route: POST /api/physics/rigid-body-add
    """
    object_name = params.get("object_name")
    rb_type = params.get("type", "ACTIVE").upper()
    shape = params.get("shape")
    mass = params.get("mass")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    valid_types = ("ACTIVE", "PASSIVE")
    if rb_type not in valid_types:
        return error_response(
            f"Unknown rigid body type '{rb_type}'. Valid: {', '.join(valid_types)}."
        )

    valid_shapes = ("BOX", "SPHERE", "CAPSULE", "CYLINDER", "CONE", "CONVEX_HULL", "MESH")
    if shape and shape.upper() not in valid_shapes:
        return error_response(
            f"Unknown collision shape '{shape}'. Valid: {', '.join(valid_shapes)}."
        )

    obj, err = _get_object(object_name)
    if err:
        return err

    if obj.rigid_body is not None:
        return error_response(
            f"Object '{object_name}' already has a rigid body. "
            "Use physics/rigid-body-configure to update settings."
        )

    try:
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.rigidbody.object_add(type=rb_type)

        rb = obj.rigid_body
        if rb is None:
            return error_response(
                f"Failed to add rigid body to '{object_name}'. "
                "Ensure the scene has a Rigid Body World (Object > Rigid Body > Add)."
            )

        if shape:
            rb.collision_shape = shape.upper()

        if mass is not None:
            rb.mass = float(mass)

        return ok_response({
            "object_name": obj.name,
            "type": rb.type,
            "collision_shape": rb.collision_shape,
            "mass": rb.mass,
        })

    except Exception as e:
        return error_response(f"Failed to add rigid body to '{object_name}': {e}")


def _handle_rigid_body_configure(params):
    """
    Configure an existing Rigid Body's settings on an object.
    Route: POST /api/physics/rigid-body-configure
    """
    object_name = params.get("object_name")
    rb_params = params.get("params") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")
    if not rb_params:
        return error_response("Parameter 'params' must be a non-empty object.")

    obj, err = _get_object(object_name)
    if err:
        return err

    rb = obj.rigid_body
    if rb is None:
        return error_response(
            f"Object '{object_name}' has no rigid body. "
            "Use physics/rigid-body-add first."
        )

    try:
        applied = {}
        skipped = {}

        for key, value in rb_params.items():
            if hasattr(rb, key):
                try:
                    current = getattr(rb, key)
                    setattr(rb, key, coerce_value(current, value))
                    applied[key] = value
                except Exception as set_err:
                    skipped[key] = str(set_err)
            else:
                skipped[key] = f"attribute '{key}' not found on RigidBodyObject"

        return ok_response({
            "object_name": obj.name,
            "applied": applied,
            "skipped": skipped,
        })

    except Exception as e:
        return error_response(f"Failed to configure rigid body on '{object_name}': {e}")


def _handle_soft_body_add(params):
    """
    Add a Soft Body modifier to a mesh object.
    Route: POST /api/physics/soft-body-add
    """
    object_name = params.get("object_name")
    sb_params = params.get("params") or {}

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if obj.modifiers.get("Softbody") is not None:
        return error_response(
            f"Object '{object_name}' already has a Soft Body modifier."
        )

    try:
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.object.modifier_add(type="SOFT_BODY")

        sb_mod = obj.modifiers.get("Softbody")
        if sb_mod is None:
            return error_response("Failed to add Soft Body modifier.")

        settings = sb_mod.settings
        applied = {}

        for key, value in sb_params.items():
            if key in SOFTBODY_CONFIGURABLE_KEYS and hasattr(settings, key):
                current = getattr(settings, key)
                setattr(settings, key, coerce_value(current, value))
                applied[key] = value

        return ok_response({
            "object_name": obj.name,
            "modifier": "Softbody",
            "applied": applied,
        })

    except Exception as e:
        return error_response(f"Failed to add Soft Body modifier to '{object_name}': {e}")


def _handle_collision_add(params):
    """
    Add a Collision modifier to a mesh object.
    Route: POST /api/physics/collision-add
    """
    object_name = params.get("object_name")
    thickness = params.get("thickness")
    friction = params.get("friction")

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    obj, err = _get_mesh_object(object_name)
    if err:
        return err

    if obj.modifiers.get("Collision") is not None:
        return error_response(
            f"Object '{object_name}' already has a Collision modifier."
        )

    try:
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.object.modifier_add(type="COLLISION")

        col_mod = obj.modifiers.get("Collision")
        if col_mod is None:
            return error_response("Failed to add Collision modifier.")

        col_settings = col_mod.settings

        if thickness is not None:
            col_settings.thickness_outer = float(thickness)

        if friction is not None:
            # In Blender, cloth friction on the collision object is 'friction_factor'
            # or 'cloth_friction' depending on version — try both
            if hasattr(col_settings, "cloth_friction"):
                col_settings.cloth_friction = float(friction)
            elif hasattr(col_settings, "friction_factor"):
                col_settings.friction_factor = float(friction)

        return ok_response({
            "object_name": obj.name,
            "modifier": "Collision",
            "thickness_outer": col_settings.thickness_outer,
        })

    except Exception as e:
        return error_response(f"Failed to add Collision modifier to '{object_name}': {e}")


def _handle_fluid_add(params):
    """
    Add a Fluid (Mantaflow) modifier to an object and configure its type.
    Route: POST /api/physics/fluid-add
    """
    object_name = params.get("object_name")
    fluid_type = params.get("type", "").upper()

    if not object_name:
        return error_response("Parameter 'object_name' is required.")

    valid_types = ("DOMAIN", "FLOW", "EFFECTOR")
    if fluid_type not in valid_types:
        return error_response(
            f"Parameter 'type' is required. Valid: {', '.join(valid_types)}."
        )

    obj, err = _get_object(object_name)
    if err:
        return err

    if obj.modifiers.get("Fluid") is not None:
        return error_response(
            f"Object '{object_name}' already has a Fluid modifier."
        )

    try:
        ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.object.modifier_add(type="FLUID")

        fluid_mod = obj.modifiers.get("Fluid")
        if fluid_mod is None:
            return error_response("Failed to add Fluid modifier.")

        fluid_mod.fluid_type = fluid_type

        return ok_response({
            "object_name": obj.name,
            "modifier": "Fluid",
            "fluid_type": fluid_mod.fluid_type,
        })

    except Exception as e:
        return error_response(f"Failed to add Fluid modifier to '{object_name}': {e}")


def _handle_bake(params):
    """
    Bake physics simulations to cache.
    Route: POST /api/physics/bake
    """
    object_name = params.get("object_name")
    start_frame = params.get("start_frame")
    end_frame = params.get("end_frame")

    try:
        if object_name:
            obj, err = _get_object(object_name)
            if err:
                return err
            ensure_context_for_object(obj)

        scene = bpy.context.scene

        if start_frame is not None:
            scene.frame_start = int(start_frame)
        if end_frame is not None:
            scene.frame_end = int(end_frame)

        with temp_override("VIEW_3D"):
            bpy.ops.ptcache.bake_all(bake=True)

        return ok_response({
            "object_name": object_name,
            "baked": True,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
        })

    except Exception as e:
        return error_response(f"Physics bake failed: {e}")


def _handle_free_bake(params):
    """
    Free (clear) physics bake cache data.
    Route: POST /api/physics/free-bake
    """
    object_name = params.get("object_name")

    try:
        if object_name:
            obj, err = _get_object(object_name)
            if err:
                return err
            ensure_context_for_object(obj)

        with temp_override("VIEW_3D"):
            bpy.ops.ptcache.free_bake_all()

        return ok_response({
            "object_name": object_name,
            "freed": True,
        })

    except Exception as e:
        return error_response(f"Physics free-bake failed: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("physics", "cloth-add", _handle_cloth_add)
register_handler("physics", "cloth-configure", _handle_cloth_configure)
register_handler("physics", "cloth-pin", _handle_cloth_pin)
register_handler("physics", "rigid-body-add", _handle_rigid_body_add)
register_handler("physics", "rigid-body-configure", _handle_rigid_body_configure)
register_handler("physics", "soft-body-add", _handle_soft_body_add)
register_handler("physics", "collision-add", _handle_collision_add)
register_handler("physics", "fluid-add", _handle_fluid_add)
register_handler("physics", "bake", _handle_bake)
register_handler("physics", "free-bake", _handle_free_bake)
