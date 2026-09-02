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
"""

import bpy
from bpy.types import Operator


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
            self.report(
                {'WARNING'},
                "No Generate action is registered for this prompt "
                f"({self.owner_type or 'unknown tab'})",
            )
            return {'CANCELLED'}
        module_name, _, function_name = operator_id.partition(".")
        try:
            op_callable = getattr(getattr(bpy.ops, module_name), function_name)
        except AttributeError:
            self.report({'WARNING'}, f"Operator {operator_id} is not available")
            return {'CANCELLED'}
        try:
            if not op_callable.poll():
                self.report(
                    {'WARNING'},
                    f"{operator_id} cannot run in the current context",
                )
                return {'CANCELLED'}
            # INVOKE so Enter behaves exactly like clicking the tab's own
            # Generate button (confirmation dialogs and reports included).
            result = op_callable('INVOKE_DEFAULT', **(props or {}))
        except RuntimeError as exc:
            self.report({'WARNING'}, str(exc))
            return {'CANCELLED'}
        return {'FINISHED'} if 'CANCELLED' not in result else {'CANCELLED'}


classes = (
    MIXIE_OT_moodboard_prompt_generate,
)
