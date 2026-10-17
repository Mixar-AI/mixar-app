# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""`mixar.agent_pick`: the one operator every row of the island's model popup runs.

The row says which source and model; this operator turns that into the
request the account needs (byok-local-models.md, "The island model picker"):

    Mixie row, Mixie answering         -> set / reset the hosted pick
    Mixie row, key in use              -> pause the key (rows deleted, record
                                          kept), THEN set the hosted pick
    Mixie row, key not pausable        -> AI Provider Settings (Remove lives there)
    key row, that key in use           -> switch the key's model in place
    key row, that key paused           -> resume the key on that model
    key row, anything else             -> AI Provider Settings
    Local row                          -> nothing (Local is picked in the dialog)
    thinking level                     -> set the hosted pick with that level

One account mutation at a time (`byok_dialog_support.account_busy`) and
never while a turn is in flight (`turn_in_flight`): the backend binds a
turn's key and model when it starts. Nor before this launch's credential
read has landed while the hosted pick says a key answers (`picker.loading`):
whether a Mixie row can pause that key is not known yet, and guessing "no"
would open the settings over a key one click could pause.
"""

import bpy
from bpy.props import EnumProperty, StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import credential_state, picker, preference_state
from ...core.picker import TAB_KEY, TAB_LOCAL, TAB_MIXIE
from . import agent_model_ops, byok_switch_ops, byok_toggle_ops
from .byok_dialog_support import TURN_IN_FLIGHT_MESSAGE, account_busy, turn_in_flight

logger = get_logger(__name__)


def _open_settings():
    result = bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')
    return {'FINISHED'} if result & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}


class MIXAR_OT_agent_pick(Operator):
    """Use this model for the agent"""

    bl_idname = "mixar.agent_pick"
    bl_label = "Pick Agent Model"
    bl_options = {'INTERNAL'}

    source: EnumProperty(items=[(t, t, "") for t in picker.TABS], default=TAB_MIXIE,
                         options={'SKIP_SAVE'})
    provider: StringProperty(default="", options={'SKIP_SAVE'})
    model: StringProperty(default="", options={'SKIP_SAVE'})
    thinking: StringProperty(default="", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        if turn_in_flight(context):
            cls.poll_message_set(TURN_IN_FLIGHT_MESSAGE)
            return False
        if account_busy():
            cls.poll_message_set(preference_state.PENDING_MESSAGE)
            return False
        if _loading():
            cls.poll_message_set(picker.LOADING_MESSAGE)
            return False
        return True

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, context):
        if turn_in_flight(context) or account_busy() or _loading():
            return {'CANCELLED'}
        wm = context.window_manager
        state = picker.picker_state(
            credential_state.snapshot(), preference_state.snapshot(),
            guest=bool(getattr(wm, "mixie_chat_is_guest", False)),
            signed_in=bool(getattr(wm, "mixie_chat_is_logged_in", True)))
        provider, model, thinking = self.provider.strip(), self.model.strip(), self.thinking.strip()

        if self.source == TAB_MIXIE:
            if not state["hosted_ok"]:
                return {'CANCELLED'}  # Mixar's models need an account (the card says so).
            if state["source"] != TAB_MIXIE or preference_state.snapshot()["mixar_agent_model_byok_active"]:
                if not state["pausable"] and not state["key_missing"]:
                    return _open_settings()
                # Key needed on this computer: there is no copy here to keep,
                # so the pick just turns the account's key off (as the chat
                # card's "Use Mixar credits instead" does) and applies the
                # hosted pick — the computer holding the key can resume it.
                hosted = _hosted(wm, provider, model, thinking, state)
                return {'FINISHED'} if byok_toggle_ops.pause(wm, then=hosted) else {'CANCELLED'}
            return {'FINISHED'} if _hosted(wm, provider, model, thinking, state)() else {'CANCELLED'}

        if self.source == TAB_KEY:
            if state["key_provider"] and provider == state["key_provider"]:
                if not model or model == state["key_model"]:
                    return {'FINISHED'}
                return {'FINISHED'} if byok_switch_ops.switch(wm, model) else {'CANCELLED'}
            if state["resumable"] and provider == state["resume_provider"]:
                return {'FINISHED'} if byok_toggle_ops.resume(wm, model or None) else {'CANCELLED'}
            return _open_settings()

        if self.source == TAB_LOCAL:
            return {'FINISHED'} if state["source"] == TAB_LOCAL else _open_settings()
        return {'CANCELLED'}


def _loading() -> bool:
    return picker.loading(credential_state.snapshot(), preference_state.snapshot())


def _hosted(wm, provider, model, thinking, state):
    """A callable that sets (or, with no model, resets) the hosted pick. The
    pick that is already current sends nothing: picking it from the Mixie tab
    while a key answers only pauses the key."""
    def run() -> bool:
        if (provider, model, thinking) == (state["hosted_provider"], state["hosted_model"],
                                           state["hosted_thinking"]):
            return True
        if not provider or not model:
            return agent_model_ops.reset_hosted(wm)
        return agent_model_ops.set_hosted(wm, provider, model, thinking)
    return run


classes = (MIXAR_OT_agent_pick,)
