# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Pause and resume the user's key: who answers, in one click.

`pause` / `resume` are what the island model card's picks run
(`agent_pick_ops.py`: a Mixie pick over a key pauses it, a key-tab pick with
the key paused resumes it); `mixar_byok.use_key` wraps the resume for AI
Provider Settings ("Use my key").

The key lives on this computer (`core/key_store`); the server keeps metadata
only. So nothing here asks for the key or deletes it:
- **Pause** (a key in use): the server's rows are deleted
  (`byok_client.delete_credentials(forget_local=False)`) so Mixie answers,
  the platform pick applies and credits are charged — and this computer
  keeps the key record. Only a key a resume could bring back is paused
  (`credential_state.pausable`): a Local key (its endpoint and managed
  runtime live outside the record), a revoked Codex sign-in or a record
  from a build that did not remember the model would be orphaned in the
  credential store, so for those Mixie opens AI Provider Settings, where
  Remove key is.
- **Resume** (a paused key): the record is re-sent
  (`byok_client.resave_stored_key`; the server re-validates it like a fresh
  save) — no dialog, no typing. With nothing to resume (no record, a Local
  key whose endpoint is not in the record, a revoked Codex sign-in, a record
  from a build that did not remember the model) and while a key is already
  in use, it opens AI Provider Settings.

Nothing is flipped ahead of the server: `credential_state.begin_toggle` only
marks the mutation in flight (the chip dims, a second mutation is refused,
background reads are held). A turn sent meanwhile reads the mirror to decide
whether to carry the key, and a guessed "inactive" would send it keyless
into a 409. The echo settles it; a failure re-reads the server and says why
in a toast. Reads of the hosted pick issued before the click are dropped
(`preference_state.invalidate_reads`) so a slower older GET can never flip
the thumb back. One mutation at a time: the operators' poll refuses while
the island has a toggle or model switch in flight, a dialog save / removal
is unanswered, or the hosted picker has a pick in flight — and while an
agent turn is in flight (`turn_in_flight`): the backend bound that turn's
key when it started, so a pause or resume now would apply only to the next
message while the chip said otherwise. `use_key` still opens the settings
meanwhile when there is nothing to resume.

`mixar_byok.forget_stored_key` (the dialog's "Forget saved key" while
paused) deletes this computer's record only; the server holds nothing.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, preference_state
from .byok_dialog_support import TURN_IN_FLIGHT_MESSAGE, turn_in_flight

logger = get_logger(__name__)

TOGGLE_TOAST_ID = "byok_toggle"


def _can_toggle() -> bool:
    # One account mutation at a time: a hosted pick in flight reverts a full
    # preference snapshot on failure, which would undo this; a dialog save /
    # removal still in flight would race this echo.
    return (not credential_state.pending() and not preference_state.mutation_pending()
            and not byok_client.mutation_in_flight())


class MIXAR_BYOK_OT_use_key(Operator):
    """Use your own API key. Switches back to the key saved on this computer, or opens AI Provider Settings"""
    bl_idname = "mixar_byok.use_key"
    bl_label = "Use My Key"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        if credential_state.resumable() and turn_in_flight(context):
            cls.poll_message_set(TURN_IN_FLIGHT_MESSAGE)
            return False
        return _can_toggle()

    def invoke(self, context, _event):
        return self.execute(context)

    def execute(self, context):
        if credential_state.resumable():
            if turn_in_flight(context):
                self.report({'WARNING'}, TURN_IN_FLIGHT_MESSAGE)
                return {'CANCELLED'}
            return {'FINISHED'} if _resume(context.window_manager) else {'CANCELLED'}
        # In use already, nothing saved here, or a saved key that must be
        # entered again: the settings are where that happens.
        return _open_settings()


def _open_settings():
    result = bpy.ops.mixar_byok.open_dialog('INVOKE_DEFAULT')
    return {'FINISHED'} if result & {'RUNNING_MODAL', 'FINISHED'} else {'CANCELLED'}


class MIXAR_BYOK_OT_forget_stored_key(Operator):
    """Delete the paused API key from this computer. Mixar's servers hold nothing for it"""
    bl_idname = "mixar_byok.forget_stored_key"
    bl_label = "Forget saved key"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return _can_toggle() and credential_state.resumable()

    def execute(self, context):
        if not _can_toggle() or not credential_state.resumable():
            return {'CANCELLED'}
        epoch = credential_state.current_epoch()

        def _done(deleted: bool):
            if credential_state.current_epoch() != epoch:
                return
            if deleted:
                credential_state.set_resumable(None)
                logger.info("BYOK paused key forgotten on this device")
            else:
                _toast(n_("Couldn't forget the saved key"), None)
            _redraw()

        byok_client.forget_stored_key(on_done=_done)
        return {'FINISHED'}


# ---------------------------------------------------------------------------
# Pause: DELETE the server rows, keep the record
# ---------------------------------------------------------------------------

def pause(wm, then=None) -> bool:
    """Ask the server to forget the key (the record stays); False when
    nothing started. ``then`` runs on the main thread after a successful
    pause — the island popup chains the hosted pick it was asked for."""
    if not _can_toggle() or not credential_state.begin_toggle(False, wm):
        return False
    epoch = credential_state.current_epoch()
    pref_epoch = preference_state.current_epoch()
    _redraw()

    def _done(success, removed_count, err):
        _on_pause_done(success, removed_count, err, epoch, pref_epoch, then)

    byok_client.delete_credentials(on_done=_done, forget_local=False)
    return True


def _on_pause_done(success, removed_count, err, epoch, pref_epoch, then=None):
    """Main-thread callback: adopt "inactive", or re-read and explain."""
    try:
        if credential_state.current_epoch() != epoch:
            return  # logged out meanwhile; `clear()` already reset everything
        # The mirrors resolve the WindowManager themselves, at call time.
        credential_state.end_pending()
        if success:
            # Every row is gone, so byok_active is false by construction:
            # move the island now (reads issued before are dropped) and let
            # the preference refresh confirm. The resumable check that
            # follows the apply tells the key tab it can switch back.
            credential_state.apply_removed(epoch=epoch)
            preference_state.invalidate_reads()
            preference_state.apply_local(
                {"mixar_agent_model_byok_active": False}, epoch=pref_epoch)
            logger.info("BYOK key paused: %d row(s) deleted, record kept on this device",
                        removed_count)
            if then is not None:
                try:
                    then()
                except Exception as e:  # noqa: BLE001 — the pause itself landed
                    logger.warning("BYOK pause follow-up failed: %s", e)
        else:
            logger.warning("BYOK pause failed: %s", err)
            _toast(n_("Couldn't switch to Mixie"), err)
            credential_state.refresh()
        # The server owns the hosted pick's byok_active; read it either way.
        preference_state.refresh()
    except Exception as e:  # noqa: BLE001 — a callback must never raise into a timer
        logger.error("BYOK pause callback failed: %s", e, exc_info=True)
    _redraw()


# ---------------------------------------------------------------------------
# Resume: re-send the record
# ---------------------------------------------------------------------------

def resume(wm, model=None) -> bool:
    """Re-send the paused key from this computer, on ``model`` (None: the
    model it was saved with); False when nothing started."""
    if not _can_toggle() or not credential_state.begin_toggle(True, wm):
        return False
    epoch = credential_state.current_epoch()
    pref_epoch = preference_state.current_epoch()
    _redraw()

    def _done(success, data, err):
        _on_resume_done(success, data, err, epoch, pref_epoch)

    byok_client.resave_stored_key(model, on_done=_done)
    return True


_resume = resume


def _on_resume_done(success, data, err, epoch, pref_epoch):
    """Main-thread callback: adopt the echo, or re-read and explain."""
    try:
        if credential_state.current_epoch() != epoch:
            return  # logged out meanwhile; `clear()` already reset everything
        credential_state.end_pending()
        if success:
            credential_state.apply_from_payload(data or {}, epoch=epoch)
            # The echo is the server's word on byok_active; keep it until the
            # preference refresh below confirms (or a slow one retries).
            preference_state.invalidate_reads()
            preference_state.apply_local(
                {"mixar_agent_model_byok_active": bool((data or {}).get("byok_active"))},
                epoch=pref_epoch)
            snap = credential_state.snapshot()
            logger.info("BYOK key resumed: provider=%s model=%s",
                        snap["byok_current_provider"], snap["byok_current_model"])
        else:
            logger.warning("BYOK resume failed: %s", err)
            _toast(n_("Couldn't switch to your API key"), err)
            # Re-derives whether the record can still be resumed (a revoked
            # Codex sign-in cannot): the island follows.
            credential_state.refresh()
        preference_state.refresh()
    except Exception as e:  # noqa: BLE001 — a callback must never raise into a timer
        logger.error("BYOK resume callback failed: %s", e, exc_info=True)
    _redraw()


# ---------------------------------------------------------------------------
# Feedback
# ---------------------------------------------------------------------------

def _toast(title, err) -> None:
    try:
        from mixar.modules.common.notifications import get_notification_store

        # One stable id: a second failed click replaces the toast.
        get_notification_store().push(
            "error", title, body=err or n_("Please try again."), ttl_ms=8000,
            id=TOGGLE_TOAST_ID,
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


def _redraw() -> None:
    try:
        from mixar.modules.common.utils.platform_utils import (
            refresh_popup_dialogs,
            trigger_ui_redraw,
        )

        trigger_ui_redraw()
        # An open settings dialog (its paused-key card) only re-runs draw()
        # when its own popup region is rebuilt.
        refresh_popup_dialogs()
    except Exception as exc:  # noqa: BLE001
        logger.debug("BYOK toggle redraw failed: %s", exc)


classes = (
    MIXAR_BYOK_OT_use_key,
    MIXAR_BYOK_OT_forget_stored_key,
)
