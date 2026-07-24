# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Project Rules operators — Python side of the rules overlay.

"Add Rules" in the chat header toggles the C++-drawn rules overlay in the
chat main region (``editors/space_mixie_chat/mixie_chat_rules_overlay.cc``)
— the same floating-card style as the past-chats overlay. The overlay
presents each rule as its own card (enable/disable toggle, pencil edit,
Global/Project scope chip, arm-to-confirm delete) above a composer box;
Enter or the Submit button saves.

All store logic lives in ``core/rules_api.py`` — the SINGLE mutation
surface shared with the agent's PROJECT_RULES tools — so these operators
are thin wrappers: the index-based contract (globals first, then this
file's rules), caps, and the WM-mirror refresh are enforced in one place.

Injection into chat messages happens in ``core/rules.py`` (first message
of a new session + mid-session update propagation).
"""

from bpy.props import IntProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...constants import CHAT_RULES_MAXLEN
from ...core import rules_api
from ...core.rules import get_raw_rules
from ...core.ui_utils import redraw_chat_areas

logger = get_logger(__name__)


def sync_rule_entries(context) -> None:
    """Rebuild the WindowManager mirror from both persisted stores."""
    del context  # the mirror lives on the WM; rules_api resolves it itself
    rules_api.refresh_rules_ui()


class MIXIE_CHAT_OT_add_rules(Operator):
    """Toggle the project-rules overlay"""
    bl_idname = "mixie_chat.add_rules"
    bl_label = "Add Rules"
    bl_description = (
        "Define rules the Mixie agent must always follow. Enabled rules "
        "are sent along with the first message of every new chat; global "
        "rules apply in every Mixar file"
    )
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, 'mixie_chat_rules')

    def execute(self, context):
        wm = context.window_manager
        opening = not getattr(wm, 'mixie_chat_rules_visible', False)
        if opening:
            # A scene created after the last edit starts with an empty
            # store while the rest of the file has one — pre-fill so the
            # overlay shows the file's rules (editing then re-mirrors).
            scene = context.scene
            if not scene.mixie_chat_rules:
                raw = get_raw_rules(scene)
                if raw:
                    scene.mixie_chat_rules = raw
            sync_rule_entries(context)
            # The rules and past-chats overlays are both modal over the
            # same chat surface — only one may be open at a time.
            if getattr(wm, 'mixie_chat_history_visible', False):
                wm.mixie_chat_history_visible = False
        wm.mixie_chat_rules_visible = opening
        redraw_chat_areas()
        return {'FINISHED'}


class _RuleOpMixin:
    """Shared poll for the C++-dispatched rule operators."""

    bl_options = {'REGISTER', 'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return context.scene is not None and hasattr(context.scene, 'mixie_chat_rules')

    def _finish(self, context, result: dict):
        if not result.get("success"):
            self.report({'WARNING'}, result.get("error", "Rule operation failed"))
            return {'CANCELLED'}
        rules_api.refresh_rules_ui()
        return {'FINISHED'}


class MIXIE_CHAT_OT_rule_add(_RuleOpMixin, Operator):
    """Append a new enabled rule to THIS file (dispatched by the C++
    overlay; promote it to global afterwards via the card's scope chip)."""

    bl_idname = "mixie_chat.rule_add"
    bl_label = "Add Rule"

    text: StringProperty(default="", maxlen=CHAT_RULES_MAXLEN,
                         options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        if not self.text.strip():
            return {'CANCELLED'}
        return self._finish(
            context, rules_api.add_rule(context.scene, self.text))


class MIXIE_CHAT_OT_rule_update(_RuleOpMixin, Operator):
    """Replace one rule's text (dispatched by the C++ overlay)."""

    bl_idname = "mixie_chat.rule_update"
    bl_label = "Save Rule"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})
    text: StringProperty(default="", maxlen=CHAT_RULES_MAXLEN,
                         options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        if not self.text.strip():
            return {'CANCELLED'}
        return self._finish(
            context, rules_api.update_rule(context.scene, self.index, text=self.text))


class MIXIE_CHAT_OT_rule_toggle(_RuleOpMixin, Operator):
    """Enable/disable one rule (dispatched by the C++ overlay)."""

    bl_idname = "mixie_chat.rule_toggle"
    bl_label = "Toggle Rule"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        resolved = rules_api.resolve_rule(context.scene, self.index)
        if resolved is None:
            return {'CANCELLED'}
        _is_global, rules, local = resolved
        enabled = not rules[local].get("enabled", True)
        return self._finish(
            context, rules_api.update_rule(context.scene, self.index, enabled=enabled))


class MIXIE_CHAT_OT_rule_delete(_RuleOpMixin, Operator):
    """Delete one rule (dispatched by the C++ overlay, arm-to-confirm)."""

    bl_idname = "mixie_chat.rule_delete"
    bl_label = "Delete Rule"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        return self._finish(
            context, rules_api.remove_rule(context.scene, self.index))


class MIXIE_CHAT_OT_rule_set_scope(_RuleOpMixin, Operator):
    """Flip one rule between global and this-file scope (dispatched by
    the C++ overlay's scope chip). Moves it between the two stores."""

    bl_idname = "mixie_chat.rule_set_scope"
    bl_label = "Change Rule Scope"

    index: IntProperty(default=-1, options={'SKIP_SAVE', 'HIDDEN'})

    def execute(self, context):
        resolved = rules_api.resolve_rule(context.scene, self.index)
        if resolved is None:
            return {'CANCELLED'}
        is_global, _rules, _local = resolved
        new_scope = rules_api.SCOPE_PROJECT if is_global else rules_api.SCOPE_GLOBAL
        return self._finish(
            context, rules_api.update_rule(context.scene, self.index, scope=new_scope))


classes = (
    MIXIE_CHAT_OT_add_rules,
    MIXIE_CHAT_OT_rule_add,
    MIXIE_CHAT_OT_rule_update,
    MIXIE_CHAT_OT_rule_toggle,
    MIXIE_CHAT_OT_rule_delete,
    MIXIE_CHAT_OT_rule_set_scope,
)
