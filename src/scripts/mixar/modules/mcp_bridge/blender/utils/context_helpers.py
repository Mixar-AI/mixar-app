"""
Context override helpers for Blender MCP Bridge.
Provides utilities for safely calling bpy.ops operators
with the correct context, supporting both Blender 3.x and 4.x.
"""

from contextlib import contextmanager

import bpy
from .compat import is_blender_4


@contextmanager
def _dict_override_context(override_dict):
    """
    Wrap a Blender 3.x override dict in a context manager so it can be used
    with 'with' statement syntax, matching the Blender 4.x temp_override API.

    Yields the override dict for compatibility with callers that may inspect it.
    """
    yield override_dict


def temp_override(area_type="VIEW_3D"):
    """
    Get a temporary context override for operator calls.

    Blender 4.x uses bpy.context.temp_override().
    Blender 3.x uses the legacy override dict approach.

    Args:
        area_type: The area type to find (default: 'VIEW_3D')

    Returns:
        Context manager for use with `with` statement (4.x)
        or override dict (3.x).
    """
    # Find the target area
    area = None
    for window in bpy.context.window_manager.windows:
        for a in window.screen.areas:
            if a.type == area_type:
                area = a
                break
        if area:
            break

    if is_blender_4():
        if area:
            region = None
            for r in area.regions:
                if r.type == "WINDOW":
                    region = r
                    break
            if region:
                return bpy.context.temp_override(
                    window=bpy.context.window,
                    area=area,
                    region=region,
                )
        # Fallback: no area found, return basic override
        return bpy.context.temp_override(window=bpy.context.window)
    else:
        # Blender 3.x legacy override dict — wrapped in a context manager
        # so all call sites can use "with temp_override(...):" uniformly.
        override = bpy.context.copy()
        if area:
            override["area"] = area
            for region in area.regions:
                if region.type == "WINDOW":
                    override["region"] = region
                    break
        return _dict_override_context(override)


def ensure_context_for_object(obj):
    """
    Ensure an object is selected and active in the current context.

    Uses the direct Python API to deselect objects instead of
    bpy.ops.object.select_all(), which requires a valid area context
    and fails in headless/background mode without a temp_override.

    Args:
        obj: The bpy object to select and make active.
    """
    for o in bpy.context.view_layer.objects:
        o.select_set(False)
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj


def ensure_viewport_context():
    """
    Ensure we have a 3D viewport context available.
    Returns a context override suitable for viewport operations.
    """
    return temp_override("VIEW_3D")


def is_valid_rna_property(obj, attr_name):
    """
    Check if attr_name is a legitimate RNA property on the given Blender object.
    Prevents arbitrary Python attribute injection via user-supplied keys.

    Args:
        obj: A Blender RNA object (modifier, constraint, preferences, etc.)
        attr_name: The attribute name string to validate.

    Returns:
        True if attr_name is a declared RNA property, False otherwise.
    """
    if not hasattr(obj, 'bl_rna'):
        # Fallback: if it's not an RNA object, just check hasattr
        return hasattr(obj, attr_name)
    rna_props = {p.identifier for p in obj.bl_rna.properties}
    return attr_name in rna_props


def safe_operator_call(operator, **kwargs):
    """
    Safely call a bpy.ops operator with error handling.

    Args:
        operator: The operator to call (e.g., bpy.ops.object.delete)
        **kwargs: Keyword arguments to pass to the operator.

    Returns:
        tuple: (success: bool, result_or_error: str)
    """
    try:
        result = operator(**kwargs)
        return (True, result)
    except RuntimeError as e:
        return (False, str(e))
    except Exception as e:
        return (False, f"{type(e).__name__}: {e}")
