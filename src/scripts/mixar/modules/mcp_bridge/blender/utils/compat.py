"""
Blender version compatibility helpers.
Handles differences between Blender 3.x, 4.x, and 5.x APIs.
Key helpers: is_blender_4(), is_blender_5(), get_action_fcurves(), get_eevee_engine_name().
"""

import bpy
import logging

logger = logging.getLogger(__name__)


def get_blender_version():
    """Get Blender version as a tuple (major, minor, patch)."""
    return tuple(bpy.app.version)


def is_blender_4():
    """Check if running Blender 4.x or later."""
    return bpy.app.version[0] >= 4


def is_blender_5():
    """Check if running Blender 5.x or later."""
    return bpy.app.version[0] >= 5


def get_action_fcurves(action, obj=None):
    """
    Get fcurves from an action, handling Blender 5.0 API changes.

    Blender 3.x/4.x: action.fcurves
    Blender 5.0+: action.layers[0].strips[0].channelbag(action_slot=obj.animation_data.action_slot).fcurves
    """
    if is_blender_5():
        if not action.layers or not action.layers[0].strips:
            return []
        strip = action.layers[0].strips[0]
        if obj is not None and hasattr(obj, 'animation_data') and obj.animation_data and hasattr(obj.animation_data, 'action_slot') and obj.animation_data.action_slot is not None:
            try:
                # Blender 5.0: strip.channelbag() expects keyword 'slot' (not 'action_slot')
                channelbag = strip.channelbag(slot=obj.animation_data.action_slot)
            except Exception as e:
                logger.warning("get_action_fcurves: channelbag() failed for '%s': %s", obj.name, e)
                return []
            if channelbag is not None:
                return channelbag.fcurves
            return []
        logger.warning("get_action_fcurves: obj is None or missing animation_data/action_slot on Blender 5.x â€” returning empty fcurves list. Pass the animated object to get proper results.")
        return []
    else:
        return action.fcurves


def get_eevee_engine_name():
    """
    Get the correct EEVEE engine identifier for the current Blender version.

    Blender 5.0+: BLENDER_EEVEE  (reverted to the original name)
    Blender 4.x:  BLENDER_EEVEE_NEXT
    Blender 3.x:  BLENDER_EEVEE

    Returns:
        str: The engine string to assign to scene.render.engine.
    """
    major = bpy.app.version[0]
    if major == 4:
        return "BLENDER_EEVEE_NEXT"
    return "BLENDER_EEVEE"


def get_auto_smooth_method():
    """
    Get the appropriate auto-smooth method for the current Blender version.

    Blender 3.x: Auto smooth is a mesh property (mesh.use_auto_smooth)
    Blender 4.x: Auto smooth is applied via a modifier

    Returns:
        str: "property" for 3.x, "modifier" for 4.x
    """
    if is_blender_4():
        return "modifier"
    return "property"


def merge_vertices(threshold=0.0001):
    """
    Merge vertices by distance, compatible across Blender versions.

    bpy.ops.mesh.remove_doubles() was removed in Blender 4.0 and replaced by
    bpy.ops.mesh.merge_by_distance(). Both accept an identical 'threshold'
    parameter. This helper abstracts the version difference so callers do not
    need to guard the version themselves.

    Must be called while the object is in Edit Mode with the target vertices
    selected.

    Args:
        threshold (float): Maximum distance between vertices to merge.
    """
    try:
        bpy.ops.mesh.merge_by_distance(threshold=threshold)
    except (AttributeError, RuntimeError):
        bpy.ops.mesh.remove_doubles(threshold=threshold)


def get_principled_input_name(name):
    """
    Map Principled BSDF input names between Blender versions.

    Blender 4.0 renamed several Principled BSDF inputs.
    This function returns the correct name for the current version.

    Args:
        name: The canonical input name (using 4.x naming)

    Returns:
        str: The correct input name for the current Blender version.
    """
    # Mapping: 4.x name -> 3.x name
    _name_map_3x = {
        "Base Color": "Base Color",  # Same in both
        "Metallic": "Metallic",      # Same in both
        "Roughness": "Roughness",    # Same in both
        "IOR": "IOR",                # Same in both
        "Alpha": "Alpha",            # Same in both
        "Normal": "Normal",          # Same in both
        "Coat Weight": "Clearcoat",
        "Coat Roughness": "Clearcoat Roughness",
        "Coat Normal": "Clearcoat Normal",
        "Sheen Weight": "Sheen",
        "Sheen Roughness": "Sheen Roughness",
        "Emission Color": "Emission",
        "Emission Strength": "Emission Strength",
        "Transmission Weight": "Transmission",
        "Specular IOR Level": "Specular",
        "Specular Tint": "Specular Tint",
        "Anisotropic": "Anisotropic",
        "Anisotropic Rotation": "Anisotropic Rotation",
        "Subsurface Weight": "Subsurface",
        "Subsurface Radius": "Subsurface Radius",
        "Subsurface Scale": "Subsurface Color",
    }

    if is_blender_4():
        return name  # 4.x uses canonical names

    return _name_map_3x.get(name, name)


def is_cast_shadow_supported():
    """
    Check if CyclesLightSettings.cast_shadow is available.

    This property was removed in Blender 5.0. FBX files exported from
    older Blender versions may reference it, causing import failures.

    Returns:
        bool: True if cast_shadow is supported (Blender < 5.0).
    """
    return not is_blender_5()
