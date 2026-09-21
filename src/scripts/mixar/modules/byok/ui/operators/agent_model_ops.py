# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Operators behind the hosted agent-model picker.

Both write OPTIMISTICALLY: the WindowManager mirror flips on the click, the
HTTP request follows on a worker thread, and a non-2xx response puts the
previous value back. A menu row that visibly does nothing for half a second
reads as a swallowed click. Send and further model changes stay disabled until
the write finishes: the server resolves the stored preference at turn start,
so an optimistic label alone is not sufficient to safely send.

Threading: the request runs on a daemon thread inside `preference_client` and
the callback is marshalled back through `bpy.app.timers`, so nothing here
touches `bpy` off the main thread. The operator instance is long gone by then,
so failures surface as a toast rather than through `self.report`.
"""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ...core import preference_client, preference_state

logger = get_logger(__name__)

_BYOK_BLOCKED_MSG = (
    "Your own API key is in use — pick \"Change or remove my API key\" in this "
    "menu to choose a hosted model"
)


def _notify_failure(title: str, message: str) -> None:
    """Surface a server-side rejection. Best-effort; never raises."""
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push("error", title, body=message or "")
    except Exception as exc:  # noqa: BLE001 — a toast must not break a save
        logger.debug("Agent model picker toast failed: %s", exc)


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Agent model picker redraw failed: %s", exc)


def _byok_active() -> bool:
    return bool(preference_state.snapshot()["mixar_agent_model_byok_active"])


class MIXAR_OT_agent_model_set(Operator):
    """Use this model for the agent"""

    bl_idname = "mixar.agent_model_set"
    bl_label = "Set Agent Model"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if preference_state.mutation_pending():
            cls.poll_message_set(preference_state.PENDING_MESSAGE)
            return False
        return True

    provider: StringProperty(name="Provider", default="")
    model: StringProperty(name="Model", default="")
    label: StringProperty(name="Label", default="")
    #: Empty means "the model's own default" and is omitted from the payload
    #: entirely, so the request bytes are unchanged for an older backend.
    thinking_level: StringProperty(name="Thinking Level", default="")

    def execute(self, context):
        provider = (self.provider or "").strip()
        model = (self.model or "").strip()
        if not provider or not model:
            self.report({'ERROR'}, "No model selected")
            return {'CANCELLED'}
        if _byok_active():
            self.report({'ERROR'}, _BYOK_BLOCKED_MSG)
            return {'CANCELLED'}

        thinking = (self.thinking_level or "").strip()
        wm = getattr(context, "window_manager", None)
        if not preference_state.begin_mutation():
            self.report({'WARNING'}, preference_state.PENDING_MESSAGE)
            return {'CANCELLED'}
        epoch = preference_state.current_epoch()
        previous = preference_state.snapshot()

        preference_state.apply_local(
            {
                "mixar_agent_model_provider": provider,
                "mixar_agent_model_id": model,
                "mixar_agent_model_label": (self.label or "").strip() or model,
                "mixar_agent_model_thinking": thinking,
                # A row the user could click was drawn eligible; the server has
                # the last word and a 400 reverts this wholesale.
                "mixar_agent_model_eligible": True,
            },
            wm,
            epoch=epoch,
        )
        _redraw()

        def _done(success, data, err):
            _on_save_done(epoch, previous, success, data, err)

        preference_client.save_preference(
            provider=provider,
            model=model,
            on_done=_done,
            thinking_level=thinking or None,
        )
        return {'FINISHED'}


class MIXAR_OT_agent_model_reset(Operator):
    """Clear the saved model and let Mixar choose"""

    bl_idname = "mixar.agent_model_reset"
    bl_label = "Reset Agent Model"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if preference_state.mutation_pending():
            cls.poll_message_set(preference_state.PENDING_MESSAGE)
            return False
        return True

    def execute(self, context):
        if _byok_active():
            self.report({'ERROR'}, _BYOK_BLOCKED_MSG)
            return {'CANCELLED'}

        wm = getattr(context, "window_manager", None)
        if not preference_state.begin_mutation():
            self.report({'WARNING'}, preference_state.PENDING_MESSAGE)
            return {'CANCELLED'}
        epoch = preference_state.current_epoch()
        previous = preference_state.snapshot()

        preference_state.apply_local(
            {
                "mixar_agent_model_provider": "",
                "mixar_agent_model_id": "",
                "mixar_agent_model_label": "",
                "mixar_agent_model_thinking": "",
                "mixar_agent_model_eligible": True,
            },
            wm,
            epoch=epoch,
        )
        _redraw()

        def _done(success, data, err):
            _on_reset_done(epoch, previous, success, err)

        preference_client.delete_preference(on_done=_done)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Main-thread callbacks
# ---------------------------------------------------------------------------

def _on_save_done(epoch, previous, success, data, err) -> None:
    """Adopt the server's echo, or put the previous pick back.

    ``epoch`` is captured before the request: a logout in between makes both
    branches a no-op, because restoring the logged-out account's model in front
    of the next user is worse than leaving the cleared default.
    """
    if epoch != preference_state.current_epoch():
        return
    if success:
        # The PUT echoes the authoritative state (including a thinking level
        # the server normalised); a follow-up GET would race it.
        if isinstance(data, dict) and data.get("items"):
            preference_state.apply_from_payload(data, epoch=epoch)
        elif isinstance(data, dict) and data.get("model"):
            # PUT returns one role view; GET returns an items envelope.
            preference_state.apply_from_payload({
                "items": [data],
                "byok_active": previous["mixar_agent_model_byok_active"],
            }, epoch=epoch)
        else:
            preference_state.end_mutation(epoch)
            preference_state.refresh()
    else:
        logger.debug("Agent model save rejected, reverting: %s", err)
        preference_state.apply_local(previous, epoch=epoch)
        # The server's message is user-safe per the contract ("Model not
        # available: ..."), and a transport failure already arrives carrying a
        # NET-* support code from `classify_network_error`. Surface it verbatim.
        _notify_failure("Could not change model", err or "")
    preference_state.end_mutation(epoch)
    _redraw()


def _on_reset_done(epoch, previous, success, err) -> None:
    if epoch != preference_state.current_epoch():
        return
    if success:
        preference_state.end_mutation(epoch)
        preference_state.refresh()
    else:
        logger.debug("Agent model reset rejected, reverting: %s", err)
        preference_state.apply_local(previous, epoch=epoch)
        _notify_failure("Could not reset model", err or "")
    preference_state.end_mutation(epoch)
    _redraw()


classes = (
    MIXAR_OT_agent_model_set,
    MIXAR_OT_agent_model_reset,
)
