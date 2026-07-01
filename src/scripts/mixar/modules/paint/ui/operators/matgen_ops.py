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
import bpy
from bpy.props import CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import Operator, PropertyGroup

from .....config.logging_config import get_logger

logger = get_logger(__name__)


class MatGenRecentItem(PropertyGroup):
    """One entry in the 'Just Generated' section."""
    material_id: StringProperty()
    display_name: StringProperty()


class MATGEN_OT_GenerateMaterial(Operator):
    """Generate a procedural material from a text prompt via the Mixar backend."""
    bl_idname = "matgen.generate_material"
    bl_label = "Generate"
    bl_description = "Generate a procedural material with AI"

    # Direct-invocation properties (agent/chat): when `query` is set, the
    # operator runs from these explicit params instead of the WindowManager UI
    # state, so the agent can call it headlessly.
    query: StringProperty(
        name="Query",
        description="Material description (direct invocation; overrides UI state)",
        default="",
    )
    pipeline: StringProperty(
        name="Pipeline",
        description="Generation pipeline: 'fast' or 'detailed'",
        default="",
    )
    from_chat: bpy.props.BoolProperty(
        name="From Chat",
        description="Called from chat/agent context",
        default=False,
    )

    @classmethod
    def poll(cls, context):
        """Disable the operator while a generation is already in flight."""
        try:
            return context.window_manager.mixar_matgen_status != "generating"
        except Exception:
            return True

    def execute(self, context):
        from mixar.modules.common.utils.agent_feedback import set_agent_gen_reason

        wm = context.window_manager

        # Direct (agent) invocation: explicit params override UI/WM state.
        if self.query.strip():
            query = self.query.strip()
            pipeline = self.pipeline.strip() or "fast"
        else:
            query = wm.mixar_matgen_query.strip()
            pipeline = wm.mixar_matgen_pipeline

        if not query:
            set_agent_gen_reason(context, "No material description provided")
            self.report({'WARNING'}, "Please enter a material description")
            return {'CANCELLED'}

        wm.mixar_matgen_status = "generating"
        for area in context.screen.areas:
            area.tag_redraw()

        try:
            from ...procedural_materials.matgen_queue import enqueue_matgen_job

            job = enqueue_matgen_job(
                prompt=query,
                pipeline=pipeline,
            )
            if job is None:
                set_agent_gen_reason(context, "Material generation already queued (duplicate)")
                wm.mixar_matgen_status = "error:Duplicate job already in queue"
                return {'CANCELLED'}
        except Exception as e:
            set_agent_gen_reason(context, str(e))
            wm.mixar_matgen_status = f"error:{e}"
            return {'CANCELLED'}

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
