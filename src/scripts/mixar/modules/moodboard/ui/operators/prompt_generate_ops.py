# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operator behind Enter-to-generate in the moodboard N-panel prompts.

The C++ text-edit handler (``interface_handlers.cc``) invokes this with the
prompt owner's RNA identifier; ``core/prompt_submit.py`` owns the routing.

The agent island's 3D / Media / Splat panes route their Generate BUTTONS
through here too, so a click and an Enter can never resolve to different paid
generations. That makes every bail-out below user-visible: a button that does
nothing and says nothing is worse than one that refuses out loud.

The island has no status bar and no Info editor, so ``self.report(...)`` alone
reaches nobody there. Every outcome below therefore ALSO writes the island's
dedicated pane-message channel — ``agent_bubble/ui/properties/
pane_message_props.py``, whose whole point is that only this dispatcher writes
it, so a pane can never paint unrelated app activity. The reports stay: they
are still the right thing for the Info editor and for anyone driving this
operator from the N-panel.
"""

import bpy
from bpy.types import Operator


def _pane_message(text, level_name):
    """Mirror `text` onto the agent island's pane-message line.

    `level_name` names one of the channel's ``LEVEL_*`` constants — resolved
    lazily so this module owns no copy of the level numbers.

    Imported defensively: the moodboard must keep working in a build (or a
    startup ordering) where the island module is not registered, so a missing
    channel silently means "the N-panel is the only surface here".
    """
    try:
        from mixar.modules.agent_bubble.ui.properties import pane_message_props
    except ImportError:
        return
    level = getattr(pane_message_props, level_name, pane_message_props.LEVEL_INFO)
    pane_message_props.set_pane_message(text, level)


class MIXIE_OT_moodboard_prompt_generate(Operator):
    bl_idname = "mixie.moodboard_prompt_generate"
    bl_label = "Generate from Prompt"
    bl_description = "Run the Generate action of the tab that owns this prompt"
    # INTERNAL: only ever invoked by the Enter handler; keeping it out of
    # search / repeat also means no last-used property replay to worry about.
    bl_options = {'INTERNAL'}

    owner_type: bpy.props.StringProperty(default="", options={'SKIP_SAVE'})

    def execute(self, context):
        from mixar.modules.moodboard.core.prompt_submit import (
            resolve_prompt_generate,
        )

        operator_id, props = resolve_prompt_generate(
            context.scene, self.owner_type
        )
        if not operator_id:
            message = (
                "No Generate action is registered for this prompt "
                f"({self.owner_type or 'unknown tab'})"
            )
            self.report({'WARNING'}, message)
            _pane_message(message, "LEVEL_WARNING")
            return {'CANCELLED'}
        module_name, _, function_name = operator_id.partition(".")
        try:
            op_callable = getattr(getattr(bpy.ops, module_name), function_name)
        except AttributeError:
            message = f"Operator {operator_id} is not available"
            self.report({'WARNING'}, message)
            _pane_message(message, "LEVEL_WARNING")
            return {'CANCELLED'}
        try:
            if not op_callable.poll():
                message = f"{operator_id} cannot run in the current context"
                self.report({'WARNING'}, message)
                _pane_message(message, "LEVEL_WARNING")
                return {'CANCELLED'}
            # INVOKE so Enter behaves exactly like clicking the tab's own
            # Generate button (confirmation dialogs and reports included).
            result = op_callable('INVOKE_DEFAULT', **(props or {}))
        except RuntimeError as exc:
            # bpy_operator.cc gives a nested call its OWN ReportList, so only
            # {'ERROR'} escapes — as a RuntimeError carrying Blender's own
            # "Error: " prefix. Re-report it at ERROR (the generation stopped;
            # the island paints it in the error colour) and strip that prefix
            # so the user reads the operator's sentence, not a doubled one.
            message = str(exc)
            if message.startswith("Error: "):
                message = message[len("Error: "):]
            self.report({'ERROR'}, message)
            _pane_message(message, "LEVEL_ERROR")
            return {'CANCELLED'}
        if 'CANCELLED' in result:
            # The inner operator refused without raising, so it reported at
            # INFO/WARNING into the OWN ReportList bpy_operator.cc gave the
            # nested call — nothing of it escaped to us or to the user. Say
            # the one thing we do know rather than bailing out silently.
            message = "Generation was cancelled"
            self.report({'WARNING'}, message)
            _pane_message(message, "LEVEL_WARNING")
            return {'CANCELLED'}
        _pane_message("Generation submitted", "LEVEL_INFO")
        return {'FINISHED'}


classes = (
    MIXIE_OT_moodboard_prompt_generate,
)
