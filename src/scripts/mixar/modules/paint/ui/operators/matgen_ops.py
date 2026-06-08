# SPDX-FileCopyrightText: 2024 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Blender operator for AI material generation via MatGen backend.

Registered classes (auto-registered by bootstrap):
- MatGenRecentItem             — PropertyGroup for recent-generation collection
- MATGEN_OT_GenerateMaterial   — spawns background thread, manages timer
- MATGEN_OT_DismissRecent      — removes an entry from the recent list

WindowManager properties (registered manually in ui.py):
- mixar_matgen_query      — prompt text field
- mixar_matgen_pipeline   — fast/detailed enum
- mixar_matgen_status     — "", "generating", "done:<name>", "error:<msg>"
- mixar_matgen_recent     — CollectionProperty(MatGenRecentItem)
"""
import queue
import threading

import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .....config.logging_config import get_logger
from ...procedural_materials import material_registry
from ...procedural_materials.matgen_client import generate_async
from ...procedural_materials.matgen_persistence import save_generated_material

logger = get_logger(__name__)

_POLL_INTERVAL = 0.25  # seconds


def _get_auth_token() -> str:
    """Return the current auth token, or empty string if unavailable."""
    try:
        from ....auth.core.auth import get_access_token
        return get_access_token() or ""
    except Exception:
        return ""


def _get_base_url() -> str:
    """Return the backend server URL."""
    try:
        from .....config.config import get_server_url
        return get_server_url() or ""
    except Exception:
        return ""


class MatGenRecentItem(PropertyGroup):
    """One entry in the 'Just Generated' section."""
    material_id: StringProperty()
    display_name: StringProperty()


class MATGEN_OT_GenerateMaterial(Operator):
    """Generate a procedural material from a text prompt via the Mixar backend."""
    bl_idname = "matgen.generate_material"
    bl_label = "Generate"
    bl_description = "Generate a procedural material with AI"

    @classmethod
    def poll(cls, context):
        """Disable the operator while a generation is already in flight."""
        try:
            return context.window_manager.mixar_matgen_status != "generating"
        except Exception:
            return True

    def execute(self, context):
        wm = context.window_manager
        query = wm.mixar_matgen_query.strip()

        if not query:
            self.report({'WARNING'}, "Please enter a material description")
            return {'CANCELLED'}

        token = _get_auth_token()
        if not token:
            wm.mixar_matgen_status = "error:Please log in to Mixar"
            return {'CANCELLED'}

        base_url = _get_base_url()
        if not base_url:
            wm.mixar_matgen_status = "error:Server URL not configured"
            return {'CANCELLED'}

        pipeline = wm.mixar_matgen_pipeline

        result_queue = queue.Queue()

        t = threading.Thread(
            target=generate_async,
            args=(query, pipeline, token, base_url, result_queue),
            daemon=True,
        )
        t.start()

        wm.mixar_matgen_status = "generating"

        for area in context.screen.areas:
            area.tag_redraw()

        bpy.app.timers.register(
            _make_poll_fn(result_queue, query),
            first_interval=_POLL_INTERVAL,
        )

        return {'FINISHED'}


class MATGEN_OT_DismissRecent(Operator):
    """Remove a material from the 'Just Generated' section."""
    bl_idname = "matgen.dismiss_recent"
    bl_label = "Dismiss"
    bl_description = "Remove from Just Generated (material stays in library)"

    index: IntProperty()

    def execute(self, context):
        wm = context.window_manager
        if 0 <= self.index < len(wm.mixar_matgen_recent):
            wm.mixar_matgen_recent.remove(self.index)
        for area in context.screen.areas:
            area.tag_redraw()
        return {'FINISHED'}


def _make_poll_fn(result_queue: queue.Queue, query: str):
    """Return a closure used as the bpy.app.timers callback.

    Returns _POLL_INTERVAL to reschedule, or None to unregister.
    """
    def poll_fn():
        # Safety: if addon was unregistered while this timer was pending, bail out
        if not hasattr(bpy.types.WindowManager, 'mixar_matgen_status'):
            return None  # Unregister timer

        try:
            result = result_queue.get_nowait()
        except queue.Empty:
            return _POLL_INTERVAL

        if not bpy.context or not bpy.context.window_manager:
            return None  # Blender context unavailable (window closed etc.)
        wm = bpy.context.window_manager

        if not result.get("ok"):
            error_msg = result.get("error", "Unknown error")
            wm.mixar_matgen_status = f"error:{error_msg}"
            logger.error("MatGen failed: %s", error_msg)
        else:
            try:
                _on_success(result, query, wm)
            except Exception as exc:
                logger.error("Failed to register generated material: %s", exc)
                wm.mixar_matgen_status = f"error:Script failed to run: {exc}"

        screen = getattr(bpy.context, 'screen', None)
        if screen:
            for area in screen.areas:
                area.tag_redraw()
        return None  # Unregister timer

    return poll_fn


def _on_success(result: dict, query: str, wm) -> None:
    """Handle a successful generation result.

    1. Save script to disk + update catalog.
    2. Register ProceduralMaterial in MaterialRegistry.
    3. Add to wm.mixar_matgen_recent (prepend).
    4. Update status string.
    """
    script = result["script"]
    archetype = result.get("archetype", "")
    # node_group_name from the backend tells us exactly what name the script
    # will create in bpy.data.node_groups — avoids heuristic lookup failures.
    node_group_name = result.get("node_group_name", "")

    mat_info = save_generated_material(
        script=script,
        query=query,
        archetype=archetype,
    )

    from ...procedural_materials.material_registry import ProceduralMaterial
    proc_mat = ProceduralMaterial(
        material_id=mat_info.material_id,
        name=mat_info.name,
        category="ai_generated",
        script_path=mat_info.script_path,  # absolute path from persistence layer
        thumbnail_path=None,
        node_group_name=node_group_name or mat_info.name,
    )
    material_registry.register_material(proc_mat)

    # Prepend to recent list
    recent = wm.mixar_matgen_recent
    new_item = recent.add()
    new_item.material_id = mat_info.material_id
    new_item.display_name = mat_info.name
    recent.move(len(recent) - 1, 0)

    wm.mixar_matgen_status = f"done:{mat_info.name}"
    logger.info("AI material '%s' registered and saved to disk", mat_info.name)


def _pipeline_items(self, context):
    return [
        ("fast", "Fast (~20s-40s)", "Skeleton-based, AST-validated"),
        ("detailed", "Detailed (~1min-2min)", "Retrieve-adapt: finds closest library material and adapts it"),
    ]


def register_wm_props():
    """Register WindowManager properties for MatGen UI state.

    MatGenRecentItem must be registered before CollectionProperty can reference
    it. Bootstrap registers ui/ modules top-down, so matgen_ops classes may not
    be auto-registered yet when ui.py calls this. Register explicitly here.
    """
    # Ensure MatGenRecentItem is registered before CollectionProperty uses it
    try:
        bpy.utils.register_class(MatGenRecentItem)
    except (ValueError, RuntimeError):
        pass  # Already registered by bootstrap — that's fine

    if not hasattr(bpy.types.WindowManager, 'mixar_matgen_query'):
        bpy.types.WindowManager.mixar_matgen_query = StringProperty(
            name="Prompt",
            description="Describe the material you want to generate",
            default="",
            maxlen=256,
        )
    if not hasattr(bpy.types.WindowManager, 'mixar_matgen_pipeline'):
        bpy.types.WindowManager.mixar_matgen_pipeline = EnumProperty(
            name="Pipeline",
            items=_pipeline_items,
            default=0,
        )
    if not hasattr(bpy.types.WindowManager, 'mixar_matgen_status'):
        bpy.types.WindowManager.mixar_matgen_status = StringProperty(
            name="Status",
            default="",
        )
    if not hasattr(bpy.types.WindowManager, 'mixar_matgen_recent'):
        bpy.types.WindowManager.mixar_matgen_recent = CollectionProperty(
            type=MatGenRecentItem,
        )


def unregister_wm_props():
    """Remove WindowManager properties."""
    for attr in ("mixar_matgen_query", "mixar_matgen_pipeline",
                 "mixar_matgen_status", "mixar_matgen_recent"):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)


# Bootstrap auto-registers this list
classes = (
    MatGenRecentItem,
    MATGEN_OT_GenerateMaterial,
    MATGEN_OT_DismissRecent,
)
