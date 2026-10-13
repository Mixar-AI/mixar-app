# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Switch the model your API key runs on, from the island's key chip.

The client never holds a key after saving it (the form's key fields are
transient and wiped on close), so this sends no key at all: `PUT /agent/byok`
with ``keep_stored_key`` makes the server reuse the key it stores for the same
provider and re-validate it against the new model (`byok_client.switch_model`).

While the request is in flight the chip names the target model, dimmed, and
the dropdown's rows are disabled (`credential_state.begin_switch`; one island
mutation at a time, shared with the Mixie | Custom AI toggle). Success
adopts the server's echo exactly like a dialog save; a failure puts the stored
model back and says why in a toast. Nothing here opens the dialog.
"""

from bpy.props import StringProperty
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, model_suggestions, preference_state

logger = get_logger(__name__)

SWITCH_TOAST_ID = "byok_switch_model"


class MIXAR_BYOK_OT_switch_model(Operator):
    """Run the agent on this model with your saved API key"""

    bl_idname = "mixar_byok.switch_model"
    bl_label = "Switch Model"
    bl_options = {'INTERNAL'}

    model: StringProperty(name="Model", options={'SKIP_SAVE'})

    @classmethod
    def poll(cls, context):
        snap = credential_state.snapshot()
        return (bool(snap["byok_is_active"]) and not credential_state.pending()
                and not byok_client.mutation_in_flight())

    def execute(self, context):
        snap = credential_state.snapshot()
        provider = snap["byok_current_provider"]
        if not snap["byok_is_active"] or not provider:
            return {'CANCELLED'}
        if not self.model or self.model == snap["byok_current_model"]:
            return {'FINISHED'}
        if not model_suggestions.is_valid_model(provider, self.model):
            self.report({'WARNING'}, n_("That model is not available for your key"))
            return {'CANCELLED'}

        if byok_client.mutation_in_flight():
            return {'CANCELLED'}  # a dialog save / removal is still in flight
        epoch = credential_state.current_epoch()
        if not credential_state.begin_switch(self.model, context.window_manager):
            return {'CANCELLED'}  # a toggle or another switch is in flight
        _redraw()

        def _done(success, data, err):
            _on_switch_done(success, data, err, epoch)

        byok_client.switch_model(provider, self.model, on_done=_done)
        return {'FINISHED'}


def _on_switch_done(success, data, err, epoch):
    """Main-thread callback: adopt the echo, or restore and explain."""
    try:
        if credential_state.current_epoch() != epoch:
            return  # logged out meanwhile; `clear()` already reset everything
        credential_state.end_pending()
        if success:
            if credential_state.apply_from_payload(data or {}, epoch=epoch):
                preference_state.refresh()
                snap = credential_state.snapshot()
                logger.info("BYOK model switched: provider=%s model=%s",
                            snap["byok_current_provider"], snap["byok_current_model"])
        else:
            logger.warning("BYOK model switch failed: %s", err)
            _toast(err)
            # The refusal may mean the key changed elsewhere (paused or
            # removed from another device): re-read so the island follows.
            credential_state.refresh()
            preference_state.refresh()
    except Exception as e:  # noqa: BLE001 — a callback must never raise into a timer
        logger.error("BYOK switch callback failed: %s", e, exc_info=True)
    _redraw()


def _toast(err) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        # One stable id: a second failed pick replaces the toast.
        get_notification_store().push(
            "error", n_("Couldn't switch model"), body=err or n_("Save failed."),
            ttl_ms=8000, id=SWITCH_TOAST_ID,
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK switch redraw failed: %s", exc)


classes = (MIXAR_BYOK_OT_switch_model,)
