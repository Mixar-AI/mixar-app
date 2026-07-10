"""
Advanced addon management handlers for Blender MCP Bridge.
Provides: addon/list, addon/enable, addon/disable, addon/preferences
"""

import bpy
import addon_utils
from ...utils.response import ok_response, error_response, coerce_value
from ...utils.context_helpers import is_valid_rna_property
from .. import register_handler


# ─── Protected addons ────────────────────────────────────────────────────────

# Addons that must not be enabled/disabled via MCP to prevent destabilising
# Blender or the MCP bridge itself.  This set blocks both the enable and
# disable handlers.  The list handler still reports them so callers can see
# their status.
_PROTECTED_ADDONS = frozenset({
    # The MCP bridge addon itself — disabling it would sever the connection.
    "blender_mcp",
    "blender_mcp_bridge",
    # Blender's built-in essential addons
    "cycles",
    "io_anim_bvh",
})


def _validate_addon_access(module_name):
    """
    Check whether the addon may be enabled/disabled via MCP.
    Returns None if allowed, or an error-response dict if blocked.
    """
    if module_name in _PROTECTED_ADDONS:
        return error_response(
            f"Addon '{module_name}' is protected and cannot be "
            "enabled/disabled through MCP."
        )
    # Reject path-traversal or shell-meta characters in module names
    if not module_name.replace("_", "").replace(".", "").isalnum():
        return error_response(
            f"Invalid addon module name '{module_name}'. "
            "Module names may only contain alphanumeric characters, "
            "underscores, and dots."
        )
    return None


# ─── Helpers ────────────────────────────────────────────────────────────────────

def _is_addon_enabled(module_name):
    """Return True if the addon with the given module name is currently enabled."""
    return module_name in bpy.context.preferences.addons.keys()


def _get_addon_prefs_snapshot(prefs_obj):
    """
    Return a dict snapshot of all user-visible properties on an AddonPreferences object.
    Skips internal Blender RNA properties (bl_idname, rna_type, etc.).
    """
    snapshot = {}
    if prefs_obj is None:
        return snapshot
    try:
        for prop in prefs_obj.bl_rna.properties:
            if prop.identifier.startswith("bl_") or prop.identifier == "rna_type":
                continue
            try:
                val = getattr(prefs_obj, prop.identifier)
                # Convert non-serialisable types to safe representations
                if hasattr(val, "__iter__") and not isinstance(val, str):
                    val = list(val)
                snapshot[prop.identifier] = val
            except Exception:
                pass  # Skip unreadable properties
    except Exception:
        pass
    return snapshot


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_addon_list(params):
    """
    List all installed Blender addons with metadata and enabled status.
    Route: POST /api/addon/list
    """
    try:
        enabled_modules = set(bpy.context.preferences.addons.keys())

        addons = []
        for mod in addon_utils.modules():
            bl_info = getattr(mod, "bl_info", {})
            module_name = mod.__name__

            # Version may be a tuple; convert to string for JSON
            version = bl_info.get("version", ())
            if isinstance(version, (tuple, list)):
                version = ".".join(str(x) for x in version)

            addons.append({
                "module_name": module_name,
                "name": bl_info.get("name", module_name),
                "description": bl_info.get("description", ""),
                "category": bl_info.get("category", ""),
                "version": version,
                "enabled": module_name in enabled_modules,
            })

        # Sort alphabetically by module name for deterministic output
        addons.sort(key=lambda a: a["module_name"])

        return ok_response({
            "addon_count": len(addons),
            "enabled_count": len(enabled_modules),
            "addons": addons,
        })
    except Exception as e:
        return error_response(f"Failed to list addons: {e}")


def _handle_addon_enable(params):
    """
    Enable a Blender addon by module name.
    Route: POST /api/addon/enable
    """
    module_name = params.get("module_name")
    if not module_name:
        return error_response("Parameter 'module_name' is required.")

    blocked = _validate_addon_access(module_name)
    if blocked:
        return blocked

    try:
        # addon_utils.enable is more reliable than the operator in background/headless contexts
        addon_utils.enable(module_name, default_set=True, persistent=True)

        enabled = _is_addon_enabled(module_name)

        return ok_response({
            "module_name": module_name,
            "enabled": enabled,
        })
    except Exception as e:
        # Fallback to the preferences operator
        try:
            bpy.ops.preferences.addon_enable(module=module_name)
            enabled = _is_addon_enabled(module_name)
            return ok_response({
                "module_name": module_name,
                "enabled": enabled,
            })
        except Exception as e2:
            return error_response(f"Failed to enable addon '{module_name}': {e} / {e2}")


def _handle_addon_disable(params):
    """
    Disable a Blender addon by module name.
    Route: POST /api/addon/disable
    """
    module_name = params.get("module_name")
    if not module_name:
        return error_response("Parameter 'module_name' is required.")

    blocked = _validate_addon_access(module_name)
    if blocked:
        return blocked

    try:
        if not _is_addon_enabled(module_name):
            return ok_response({
                "module_name": module_name,
                "enabled": False,
                "note": "Addon was already disabled.",
            })

        addon_utils.disable(module_name, default_set=True)

        enabled = _is_addon_enabled(module_name)

        return ok_response({
            "module_name": module_name,
            "enabled": enabled,
        })
    except Exception as e:
        # Fallback to the preferences operator
        try:
            bpy.ops.preferences.addon_disable(module=module_name)
            enabled = _is_addon_enabled(module_name)
            return ok_response({
                "module_name": module_name,
                "enabled": enabled,
            })
        except Exception as e2:
            return error_response(f"Failed to disable addon '{module_name}': {e} / {e2}")


def _handle_addon_preferences(params):
    """
    Read or update an addon's AddonPreferences properties.
    Route: POST /api/addon/preferences
    """
    module_name = params.get("module_name")
    updates = params.get("params") or {}

    if not module_name:
        return error_response("Parameter 'module_name' is required.")

    try:
        if not _is_addon_enabled(module_name):
            return error_response(
                f"Addon '{module_name}' is not enabled. Enable it first with blender_addon_enable."
            )

        addon_entry = bpy.context.preferences.addons.get(module_name)
        if addon_entry is None:
            return error_response(
                f"Addon '{module_name}' is listed as enabled but has no preferences entry."
            )

        prefs = addon_entry.preferences  # May be None if no AddonPreferences defined

        if prefs is None:
            if updates:
                return error_response(
                    f"Addon '{module_name}' does not define an AddonPreferences class; "
                    "no preferences can be set."
                )
            return ok_response({
                "module_name": module_name,
                "preferences": {},
                "note": "This addon has no AddonPreferences class.",
            })

        # Apply requested updates
        applied = {}
        failed = {}
        for key, value in updates.items():
            if not is_valid_rna_property(prefs, key):
                failed[key] = f"'{key}' is not a valid preference property"
                continue
            try:
                current = getattr(prefs, key, None)
                if current is not None:
                    value = coerce_value(current, value)
                setattr(prefs, key, value)
                applied[key] = value
            except (AttributeError, TypeError) as ex:
                failed[key] = str(ex)

        # Return a full snapshot of current preference state
        snapshot = _get_addon_prefs_snapshot(prefs)

        result = {
            "module_name": module_name,
            "preferences": snapshot,
        }
        if applied:
            result["applied"] = applied
        if failed:
            result["failed"] = failed

        return ok_response(result)
    except Exception as e:
        return error_response(f"Failed to access addon preferences for '{module_name}': {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("addon", "list",        _handle_addon_list)
register_handler("addon", "enable",      _handle_addon_enable)
register_handler("addon", "disable",     _handle_addon_disable)
register_handler("addon", "preferences", _handle_addon_preferences)
