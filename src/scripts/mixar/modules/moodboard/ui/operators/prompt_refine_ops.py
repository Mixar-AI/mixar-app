# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Refine / Revert operators for generation prompts.

Two operators serve both surfaces — the moodboard N-panel tabs and the
inference-graph node cards — because they are the same action on two kinds of
field. Which field is addressed by ``node_id`` (a canvas node) or ``owner``
(the RNA identifier of the tab PropertyGroup that owns the prompt); the
engine in ``core.prompt_refine`` resolves either into one slot.

Both properties are ``SKIP_SAVE``: these are ``REGISTER`` operators, so
Blender would otherwise refill an unset property from the previous run and a
Refine pressed on one node would re-refine whichever node was refined last —
the same trap ``run_action_node`` and ``moodboard_graph_select`` document.

Neither operator is ``UNDO``. Writing a prompt string is not a scene edit
worth a stack entry, and pushing one would make Ctrl+Z ambiguous with the
Revert button sitting right beside it — which is the affordance that exists
precisely so an unwanted refinement can be taken back.
"""

import bpy
from bpy.types import Operator

from mixar.modules.moodboard.core import prompt_refine


def _resolve_slot(context, node_id: str, owner: str):
    """The slot addressed by this invocation, or None."""
    scene = getattr(context, "scene", None)
    if scene is None:
        return None
    if node_id:
        return prompt_refine.node_slot(scene, node_id)
    return prompt_refine.sidebar_slot(scene, owner)


class MIXIE_OT_refine_prompt(Operator):
    """Rewrite this prompt for the model it will be sent to"""

    bl_idname = "mixie.refine_prompt"
    bl_label = "Refine Prompt"
    bl_description = (
        "Rewrite this prompt for the model it will be sent to, adding the "
        "detail that model responds to. Revert puts your own wording back"
    )
    bl_options = {'REGISTER'}

    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    owner: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        slot = _resolve_slot(context, self.node_id, self.owner)
        if slot is None:
            self.report({'WARNING'}, "No prompt to refine here")
            return {'CANCELLED'}
        if slot.is_running():
            # Not an error: the user pressed a button that is already busy.
            return {'CANCELLED'}

        def _on_done(success, message):
            if not message:
                return
            # The operator has long since returned by the time the request
            # lands, so its own report() would go nowhere — the toast store
            # is the surface that still exists.
            _notify(success, message)

        if not prompt_refine.refine(slot, _on_done):
            return {'CANCELLED'}
        return {'FINISHED'}


class MIXIE_OT_revert_prompt(Operator):
    """Put your own wording back"""

    bl_idname = "mixie.revert_prompt"
    bl_label = "Revert Prompt"
    bl_description = "Restore the prompt you wrote before it was refined"
    bl_options = {'REGISTER'}

    node_id: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})
    owner: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        slot = _resolve_slot(context, self.node_id, self.owner)
        if slot is not None and slot.is_running():
            self.report({'WARNING'}, "Wait for the refinement to finish")
            return {'CANCELLED'}
        if slot is None or not prompt_refine.revert(slot):
            self.report({'WARNING'}, "Nothing to revert to")
            return {'CANCELLED'}
        return {'FINISHED'}


def _notify(success: bool, message: str) -> None:
    """Surface a late result without an operator to report through."""
    try:
        from mixar.modules.common.notifications import get_notification_store

        # One stable id: a second refinement replaces the first toast rather
        # than stacking messages about the same button.
        get_notification_store().push(
            "success" if success else "warning",
            message,
            id="mixar.prompt_refine",
        )
    except Exception:
        # A missing toast must never be the thing that breaks a refinement
        # the user can already see landed in the field.
        from mixar.config.logging_config import get_logger

        get_logger(__name__).info("[PromptRefine] %s", message)


classes = (
    MIXIE_OT_refine_prompt,
    MIXIE_OT_revert_prompt,
)
