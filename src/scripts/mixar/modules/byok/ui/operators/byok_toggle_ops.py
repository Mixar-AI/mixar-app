# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The island's Mixie | Custom AI toggle: switch who answers, in one click.

The toggle never deletes a key and Mixie never opens AI Provider settings:
- **Mixie** while a key is in use pauses the stored key (`PUT /agent/byok/state`
  `{"enabled": false}`); Mixie answers and the platform pick applies.
- **Custom AI** resumes a paused key that still validates — no dialog, no key
  re-entry. With no key stored (or one that must be entered again), and while
  a key is already in use, it opens AI Provider settings.

The flip is optimistic: the credential mirror (`credential_state.begin_toggle`)
and the hosted pick's `byok_active` (what the thumb and the hosted menu read)
move at once, background fetches are held off, and the echo or a failure
settles it — a failure restores both, re-reads the server and says why in a
toast; success adopts the echo's `byok_active` and re-reads the preference.
Reads issued before the click are dropped (`invalidate_reads`) so a slower
older GET can never flip the thumb back. One mutation
at a time: the operators' poll refuses while the island has a toggle or model
switch in flight, or the hosted picker has a pick in flight.

Two operators, not `open_dialog` with a property: the toggle's halves are
adjacent unlabelled buttons, and when the island rebuilds its block Blender
matches the active button to its predecessor by operator type, so two
`open_dialog` buttons could trade their properties after a layout change.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, preference_state

logger = get_logger(__name__)

TOGGLE_TOAST_ID = "byok_toggle"


def _can_toggle() -> bool:
    # One account mutation at a time: a hosted pick in flight reverts a full
    # preference snapshot on failure, which would undo this flip.
    # (and a dialog save / removal still in flight would race this echo).
    return (not credential_state.pending() and not preference_state.mutation_pending()
            and not byok_client.mutation_in_flight())


class MIXAR_BYOK_OT_use_mixie(Operator):
    """Switch to Mixie, Mixar's hosted models. Your API key stays saved: Custom AI switches back"""
    bl_idname = "mixar_byok.use_mixie"
    bl_label = "Use Mixie"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _can_toggle()

    def execute(self, context):
        # Either mirror may be the first to say a key is in use (the island's
        # thumb reads the hosted pick's flag); Mixie already answering is a no-op.
        if not (credential_state.snapshot()["byok_is_active"]
                or preference_state.snapshot()["mixar_agent_model_byok_active"]):
            return {'CANCELLED'}
        return {'FINISHED'} if _toggle(False, context.window_manager) else {'CANCELLED'}


class MIXAR_BYOK_OT_use_key(Operator):
    """Use your own API key. Switches back to your saved key, or opens AI Provider settings"""
    bl_idname = "mixar_byok.use_key"
    bl_label = "Use Custom AI"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _can_toggle()

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, context):
        if credential_state.resumable():
            return {'FINISHED'} if _toggle(True, context.window_manager) else {'CANCELLED'}
        # In use already, nothing stored, or a stored key that must be entered
        # again: the settings are where that happens.
        result = bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')
        return {'FINISHED'} if result & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}


def _toggle(enabled: bool, wm) -> bool:
    """Flip the island now and ask the server; False when nothing started."""
    if not _can_toggle():
        return False
    pref_before = preference_state.snapshot()["mixar_agent_model_byok_active"]
    if not credential_state.begin_toggle(enabled, wm):
        return False
    pref_epoch = preference_state.current_epoch()
    # A preference GET already in flight (a previous toggle's refresh, login,
    # a retry) carries the old byok_active and would flip the thumb back.
    preference_state.invalidate_reads()
    preference_state.apply_local({"mixar_agent_model_byok_active": enabled}, wm)
    epoch = credential_state.current_epoch()
    _redraw()

    def _done(success, data, err):
        _on_toggle_done(enabled, success, data, err, epoch, pref_epoch, pref_before)

    byok_client.set_key_enabled(enabled, on_done=_done)
    return True


def _on_toggle_done(enabled, success, data, err, epoch, pref_epoch, pref_before):
    """Main-thread callback: keep the echo, or restore, re-read and explain."""
    try:
        if credential_state.current_epoch() != epoch:
            return  # logged out meanwhile; `clear()` already reset everything
        if success:
            credential_state.end_pending()
            credential_state.apply_from_payload(data or {}, epoch=epoch)
            # The echo is the server's word on byok_active; keep it until the
            # preference refresh below confirms (or a slow one retries).
            preference_state.invalidate_reads()
            preference_state.apply_local(
                {"mixar_agent_model_byok_active": bool((data or {}).get("byok_active"))},
                epoch=pref_epoch)
            logger.info("BYOK key %s", "resumed" if enabled else "paused")
        else:
            logger.warning("BYOK %s failed: %s", "resume" if enabled else "pause", err)
            credential_state.end_pending(restore=True)
            preference_state.invalidate_reads()
            preference_state.apply_local(
                {"mixar_agent_model_byok_active": pref_before}, epoch=pref_epoch)
            _toast(enabled, err)
            credential_state.refresh()
        # The server owns the hosted pick's byok_active; read it either way.
        preference_state.refresh()
    except Exception as e:  # noqa: BLE001 — a callback must never raise into a timer
        logger.error("BYOK toggle callback failed: %s", e, exc_info=True)
    _redraw()


def _toast(enabled, err) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        title = (n_("Couldn't switch to your API key") if enabled
                 else n_("Couldn't switch to Mixie"))
        # One stable id: a second failed click replaces the toast.
        get_notification_store().push(
            "error", title, body=err or n_("Please try again."), ttl_ms=8000,
            id=TOGGLE_TOAST_ID,
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import trigger_ui_redraw

        trigger_ui_redraw()
        # An open settings dialog (its Use This Key / paused strip) only
        # re-runs draw() when its own popup region is refreshed.
        from . import byok_dialog_refresh
        byok_dialog_refresh.refresh()
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK toggle redraw failed: %s", exc)


classes = (MIXAR_BYOK_OT_use_mixie, MIXAR_BYOK_OT_use_key)
