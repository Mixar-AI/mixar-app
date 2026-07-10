"""
Scene extended handlers for Blender MCP Bridge.
Provides: scene/cleanup
"""

import bpy
from ...utils.response import ok_response, error_response
from .. import register_handler


# ─── Handlers ───────────────────────────────────────────────────────────────────

def _handle_scene_cleanup(params):
    """
    Purge unused (orphaned) data-blocks from the Blender file.
    Route: POST /api/scene/cleanup
    """
    types = params.get("types", ["all"])

    if not isinstance(types, list):
        return error_response("Parameter 'types' must be an array.")

    valid_types = {"meshes", "materials", "textures", "all"}
    for t in types:
        if t not in valid_types:
            return error_response(
                f"Invalid type '{t}'. Valid values: {', '.join(sorted(valid_types))}."
            )

    try:
        removed = 0

        if "all" in types:
            # Full recursive orphan purge — handles all data types
            removed = bpy.data.orphans_purge(
                do_local_ids=True,
                do_linked_ids=False,
                do_recursive=True,
            )
        else:
            # Targeted per-type removal of zero-user data-blocks
            if "meshes" in types:
                to_remove = [m for m in bpy.data.meshes if m.users == 0]
                for m in to_remove:
                    bpy.data.meshes.remove(m)
                    removed += 1

            if "materials" in types:
                to_remove = [m for m in bpy.data.materials if m.users == 0]
                for m in to_remove:
                    bpy.data.materials.remove(m)
                    removed += 1

            if "textures" in types:
                to_remove = [t for t in bpy.data.textures if t.users == 0]
                for t in to_remove:
                    bpy.data.textures.remove(t)
                    removed += 1

        return ok_response({
            "types":   types,
            "removed": removed,
        })
    except Exception as e:
        return error_response(f"Scene cleanup failed: {e}")


# ─── Register routes ─────────────────────────────────────────────────────────────

register_handler("scene", "cleanup", _handle_scene_cleanup)
