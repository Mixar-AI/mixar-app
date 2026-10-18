# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK operators: dialog + save/remove actions.

The server stores BYOK METADATA only (provider, model, masked preview); the
key itself is written to this device's credential store by
`core/byok_client.save_credentials` on a 200 and attached to every agent
turn by `core/turn_credentials`. A device without a stored key (upgrade,
second machine) sees `wm.byok_device_key_missing` and the dialog asks for
the key only — re-saving goes through PUT /agent/byok again.

State machine lives on WindowManager (see ui/properties/byok_props.py);
`byok_dialog_ui.draw_dialog` renders it with a single-primary-action footer
whose active-default button suppresses the props dialog's OK/Cancel row.
Save and Remove spawn async work through `core/byok_client.py`; callbacks
mutate WM state on the main thread. Success lands on an explicit SAVED /
REMOVED recap with one Done button. The island's toggle and model switch
mutate the same key, so every write here waits for them (`account_busy`).
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.ui.constants import CARD_DIALOG_WIDTH
from mixar.modules.common.i18n import n_

from ...core import byok_client, credential_state, model_suggestions, models_cache
from ...core import key_prompt, preference_state
from ...core.local_switch import (
    deregister_local_if_switched_away as _deregister_local_if_switched_away,
)
from . import byok_codex_ops, byok_dialog_support, byok_dialog_ui
from .byok_dialog_support import (
    account_busy as _account_busy,
    prefill_from_prompt as _prefill_from_prompt,
    saved_provider_model as _saved_provider_model,
    toast_if_closed,
)
from .byok_state_ops import (
    _apply_cached_state,
    _clear_cached_state,
    _redraw_mixie_chat_areas,
    ensure_dialog_redraw_pump,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _wipe_form_secrets(wm):
    """Remove transient API/token material from the live WindowManager."""
    for attr in (
        'byok_form_api_key',
        'byok_form_local_custom_key',
    ):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dialog entry point
# ---------------------------------------------------------------------------

def _dialog_host_window(context):
    """The main window the dialog should open over, or None to stay put.

    An Agent Bubble window (island or pill) is a small always-on-top overlay:
    a props dialog opened there is clipped to its height. Prefer the window
    with the most areas that is NOT a bubble — the primary workspace window.
    """
    try:
        from mixar.modules.agent_bubble.core.bubble_lifecycle import (
            is_agent_bubble_window,
        )
    except Exception:  # noqa: BLE001 — stripped builds: stay in place
        return None
    try:
        if not is_agent_bubble_window(context.window):
            return None
        candidates = [w for w in context.window_manager.windows
                      if not is_agent_bubble_window(w) and w.screen.areas]
    except Exception:  # noqa: BLE001
        return None
    if not candidates:
        return None
    return max(candidates, key=lambda w: len(w.screen.areas))


# True while the props dialog is on screen. Re-invoking would stack another
# dialog (and reset the form state under the one already open), so invoke()
# refuses while set; execute()/cancel() clear it when the dialog closes.
_dialog_open = False


class MIXAR_BYOK_OT_open_dialog(Operator):
    """Configure your own API provider and key for the Mixar agent"""
    bl_idname = "mixar_byok.open_dialog"
    bl_label = "AI Provider Settings"
    bl_description = (
        "Use your own API key for the Mixar agent. "
        "While active, Mixar credits are not charged for agent requests."
    )

    def invoke(self, context, event):
        global _dialog_open
        if _dialog_open:
            return {'CANCELLED'}
        wm = context.window_manager
        # Reset dialog-local state on open — unless a save / remove is still
        # in flight, whose SAVING / REMOVING the dialog keeps showing until it
        # lands (the dialog can be closed with Esc mid-request). Never prefill
        # the api_key field.
        if not byok_client.mutation_in_flight():
            wm.byok_dialog_state = 'IDLE'
            wm.byok_last_error = ''
        _wipe_form_secrets(wm)  # never prefill credential material
        byok_codex_ops.prefill_path(wm)  # a path, not a credential
        # If a key is saved (in use, or paused on this computer), prefill
        # provider/model so the user sees what's currently saved and can edit
        # from there. Provider assignment can fail if the cache hasn't been
        # populated yet (the saved provider isn't in the current EnumProperty
        # items) — guard against TypeError.
        saved_provider, saved_model = _saved_provider_model(wm)
        if saved_provider:
            try:
                wm.byok_form_provider = saved_provider
            except TypeError:
                logger.debug("Could not prefill provider %s — not in cache yet", saved_provider)
            if model_suggestions.is_openrouter(saved_provider):
                # OpenRouter uses a free-text model slug, not the catalog dropdown.
                if saved_model:
                    wm.byok_form_openrouter_model = saved_model
            elif model_suggestions.is_local(saved_provider):
                pass  # prefilled below by byok_local_ops.prepare_dialog
            elif saved_model:
                try:
                    wm.byok_form_model = saved_model
                except TypeError:
                    logger.debug(
                        "Could not prefill model %s — not in cache for this provider",
                        saved_model,
                    )
        # Opened from the chat's key-missing card: the refusal's provider and
        # model win over the mirror, and the form draws key-only with the
        # credential field focused (`core/key_prompt`).
        _prefill_from_prompt(wm, key_prompt.take())
        # If the provider+model cache is empty, kick off a fetch so the
        # dropdown becomes populated by the time the user picks. (Belt-
        # and-suspenders — the auth login hook normally fires this already.)
        if not model_suggestions.is_loaded():
            models_cache.refresh()
        # Local provider: refresh the managed-model item cache and prefill
        # mode/model from the last registration (cheap; guarded — the local
        # runtime module may be unavailable in stripped builds).
        try:
            from . import byok_local_ops
            byok_local_ops.prepare_dialog(wm)
        except Exception as e:
            logger.debug("Local provider dialog prep failed: %s", e)
        # A props dialog (not invoke_popup) redraws continuously, so the async
        # SAVING → IDLE / ERROR flips show without user input. The native
        # modal dialog opens it in the main window, centred, with the Agent
        # island and pill hidden (they float above every main-window pop-up);
        # the pop-up's own teardown releases that hold on every close path
        # (Done, Cancel, Esc, click-away, file load).
        _dialog_open = True
        modal = getattr(wm, "mixar_invoke_modal_dialog", None)
        if modal is not None:
            try:  # either call raising must release the single-instance flag
                try:  # the designer's sheet: no title row, framed card behind
                    return modal(self, width=byok_dialog_ui.SHEET_WIDTH, sheet=True)
                except TypeError as exc:  # a binary predating `sheet`: plain dialog
                    if "sheet" not in str(exc):
                        raise
                    return modal(self, width=byok_dialog_ui.SHEET_WIDTH)
            except Exception:
                _dialog_open = False
                raise
        # Binaries without it: a popup block in the Agent Bubble's ~460px
        # window would be clipped over the composer, so host it in the main
        # window instead. Override the WINDOW only: the bubble's screen is a
        # temporary one and `temp_override(screen=...)` refuses it outright
        # ("Overriding context with an active temporary screen isn't
        # supported").
        host = _dialog_host_window(context)
        try:
            if host is not None and host != context.window:
                with context.temp_override(window=host):
                    return wm.invoke_props_dialog(self, width=CARD_DIALOG_WIDTH)
            return wm.invoke_props_dialog(self, width=CARD_DIALOG_WIDTH)
        except Exception:
            _dialog_open = False
            raise

    def execute(self, context):
        global _dialog_open
        _dialog_open = False
        # No-op: Save / Remove are their own operators, invoked from draw().
        _wipe_form_secrets(context.window_manager)
        key_prompt.dismiss(saving=_saving(context.window_manager))
        return {'FINISHED'}

    def cancel(self, context):
        """Esc/click-away must not leave JWTs or API keys in RNA memory."""
        global _dialog_open
        _dialog_open = False
        _wipe_form_secrets(context.window_manager)
        # A save still in flight keeps the card's resend request for its echo.
        key_prompt.dismiss(saving=_saving(context.window_manager))

    def draw(self, context):
        # All rendering lives in byok_dialog_ui (500-line rule): the
        # card-styled states AND the single-primary-action footer whose
        # active-default button suppresses the native OK/Cancel row.
        byok_dialog_ui.draw_dialog(self.layout, context.window_manager)


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_save(Operator):
    """Validate with the provider and save your API key"""
    bl_idname = "mixar_byok.save"
    bl_label = "Save"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        # In-flight guard only. Field validation deliberately lives in
        # execute(), which routes problems to the ERROR state with a
        # message the user can act on — the old silently-greyed Save
        # button gave no clue what was missing (and the card-styled
        # button has no disabled look to lean on). The island's toggle /
        # model switch is a mutation of the same key: one at a time, or a
        # late echo would resurrect what this changes.
        return (context.window_manager.byok_dialog_state not in ('SAVING', 'REMOVING')
                and not _account_busy())

    def execute(self, context):
        wm = context.window_manager
        if wm.byok_dialog_state in ('SAVING', 'REMOVING') or _account_busy():
            return {'CANCELLED'}
        provider = wm.byok_form_provider

        if model_suggestions.is_openrouter(provider):
            return self._execute_openrouter(wm)
        if model_suggestions.is_codex(provider):
            return self._execute_codex(wm)
        if model_suggestions.is_local(provider):
            return self._execute_local(wm)

        model = wm.byok_form_model
        api_key = wm.byok_form_api_key.strip()

        # Name what is actually missing (a picked model is never asked for again).
        problem = (n_("Pick a provider.") if provider == 'NONE' else n_("Pick a model.")
                   if not model_suggestions.is_valid_model(provider, model)
                   else n_("Enter your API key.") if not api_key else "")
        if problem:
            wm.byok_dialog_state, wm.byok_last_error = 'ERROR', problem
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()
        ensure_dialog_redraw_pump()

        byok_client.save_credentials(
            provider=provider,
            model=model,
            api_key=api_key,
            on_done=_save_callback(),
        )
        return {'FINISHED'}

    def _execute_openrouter(self, wm):
        """OpenRouter save: no client-side ping — the backend can reach
        OpenRouter directly, so it validates the key + model slug on Save."""
        model = wm.byok_form_openrouter_model.strip()
        api_key = wm.byok_form_api_key.strip()
        if not model or not api_key:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = n_("Enter a model slug and your key.")
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()
        ensure_dialog_redraw_pump()

        byok_client.save_credentials(
            provider='openrouter',
            model=model,
            api_key=api_key,
            on_done=_save_callback(),
        )
        return {'FINISHED'}

    def _execute_local(self, wm):
        """Local save: managed requires the supervised server healthy;
        custom pings the user's server off-thread first. Both end in the
        same PUT /agent/byok (with base_url + supports_vision) and the
        shared save callback."""
        from . import byok_local_ops
        result = byok_local_ops.execute_local(self, wm, on_done=_save_callback())
        _redraw_mixie_chat_areas()
        return result

    def _execute_codex(self, wm):
        """Codex save: the auth.json bundle is parsed on this machine and only
        the access token + ChatGPT account id reach the server; the refresh
        token stays in this device's credential store (byok_codex_ops)."""
        result = byok_codex_ops.execute_codex(self, wm, on_done=_save_callback())
        _redraw_mixie_chat_areas()
        return result


def _saving(wm) -> bool:
    return getattr(wm, 'byok_dialog_state', '') == 'SAVING'


def _save_callback():
    """Bind the submit-time credential epoch into the save callback.

    The PUT is async; if the user logs out before it lands, the echo must not
    write the logged-out account's provider back into the mirror.
    """
    epoch = credential_state.current_epoch()

    def _done(success: bool, data, err):
        _on_save_done(success, data, err, epoch=epoch)

    return _done


def _on_save_done(success: bool, data, err, epoch=None):
    """Main-thread save callback."""
    try:
        wm = bpy.context.window_manager
        if success:
            applied = _apply_cached_state(wm, data or {}, epoch)
            _wipe_form_secrets(wm)
            if not applied:
                logger.debug("BYOK save landed after logout; echo dropped")
                wm.byok_dialog_state = 'IDLE'
                return
            # The echo is the server's word: move the island now (reads issued
            # before it are dropped), and let the refresh confirm.
            preference_state.invalidate_reads()
            preference_state.apply_local(
                {'mixar_agent_model_byok_active': bool((data or {}).get('byok_active'))}, wm)
            preference_state.refresh()
            # SAVED, not IDLE: the dialog shows an explicit recap with a
            # single Done button, so the user never has to wonder
            # whether the save landed.
            wm.byok_dialog_state = 'SAVED'
            wm.byok_last_error = ''
            logger.info("BYOK saved: provider=%s model=%s", wm.byok_current_provider, wm.byok_current_model)
            _deregister_local_if_switched_away(wm.byok_current_provider)
            # Opened from the chat's key-missing card: resend the refused
            # message now that this device can sign it (once).
            key_prompt.notify_saved()
            byok_dialog_support.settle_sign_in_notice()
        else:
            if epoch is not None and epoch != credential_state.current_epoch():
                wm.byok_dialog_state = 'IDLE'
                return  # another account by now; nothing of this save remains
            if data:
                # The PUT landed but the device-store write did not: adopt
                # the server's state so the card and the "Key needed on this
                # device" pill tell the truth behind the error.
                _apply_cached_state(wm, data, epoch)
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or n_("Couldn't save. Try again.")
            logger.warning("BYOK save failed: %s", err)
            toast_if_closed(_dialog_open, n_("Couldn't save your API key"), err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK save callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Remove (two-click confirm)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_request_remove(Operator):
    """Start the remove-confirmation flow"""
    bl_idname = "mixar_byok.request_remove"
    bl_label = "Remove"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        wm.byok_dialog_state = 'CONFIRM_REMOVE'
        wm.byok_last_error = ''  # the confirm step shows only its own failure
        return {'FINISHED'}


class MIXAR_BYOK_OT_cancel_remove(Operator):
    """Cancel the remove flow and return to the main dialog"""
    bl_idname = "mixar_byok.cancel_remove"
    bl_label = "Cancel"
    bl_options = {'INTERNAL'}

    def execute(self, context):
        wm = context.window_manager
        wm.byok_dialog_state = 'IDLE'
        wm.byok_last_error = ''
        return {'FINISHED'}


class MIXAR_BYOK_OT_confirm_remove(Operator):
    """Delete your API key: from your Mixar account and from this computer"""
    bl_idname = "mixar_byok.confirm_remove"
    bl_label = "Confirm Remove"
    bl_options = {'INTERNAL'}

    @classmethod
    def poll(cls, context):
        return (context.window_manager.byok_dialog_state not in ('SAVING', 'REMOVING')
                and not _account_busy())

    def execute(self, context):
        wm = context.window_manager
        if wm.byok_dialog_state in ('SAVING', 'REMOVING') or _account_busy():
            return {'CANCELLED'}
        wm.byok_dialog_state = 'REMOVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()
        ensure_dialog_redraw_pump()

        epoch = credential_state.current_epoch()

        def _done(success: bool, removed_count: int, err):
            _on_delete_done(success, removed_count, err, epoch=epoch)

        byok_client.delete_credentials(on_done=_done)
        return {'FINISHED'}


def _on_delete_done(success: bool, removed_count: int, err, epoch=None):
    """Main-thread delete callback."""
    try:
        wm = bpy.context.window_manager
        if epoch is not None and epoch != credential_state.current_epoch():
            # Logged out (or into another account) meanwhile: this result
            # belongs to an account the mirror no longer shows.
            wm.byok_dialog_state = 'IDLE'
            return
        if success:
            # The server confirmed "inactive": the mirror stays LOADED (a
            # logout clears it unloaded), so nothing reads it as unfetched.
            _clear_cached_state(wm, loaded=True)
            _wipe_form_secrets(wm)
            # Every row is gone, so byok_active is false by construction: move
            # the island now (reads issued before are dropped), refresh confirms.
            preference_state.invalidate_reads()
            preference_state.apply_local({'mixar_agent_model_byok_active': False}, wm)
            preference_state.refresh()
            # REMOVED, not IDLE — explicit recap, same as the save path.
            wm.byok_dialog_state = 'REMOVED'
            wm.byok_last_error = ''
            logger.info("BYOK removed: %d row(s) deleted", removed_count)
            _deregister_local_if_switched_away(None)
        else:
            # Back on the confirm step, error shown: Remove retries, Keep backs
            # out (the form's Try Again would re-run Save with no key).
            wm.byok_dialog_state = 'CONFIRM_REMOVE'
            wm.byok_last_error = err or n_("Couldn't switch back. Try again.")
            logger.warning("BYOK remove failed: %s", err)
            toast_if_closed(_dialog_open, n_("Couldn't remove your API key"), err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK delete callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Registration (picked up by bootstrap auto-discovery)
# ---------------------------------------------------------------------------
# The fetch operators (mixar_byok.fetch_state / fetch_models_catalog)
# and the cached-state mirror live in byok_state_ops.py; the Codex
# load/paste operators in byok_codex_ops.py; Local in byok_local_ops.py.

classes = (
    MIXAR_BYOK_OT_open_dialog,
    MIXAR_BYOK_OT_save,
    MIXAR_BYOK_OT_request_remove,
    MIXAR_BYOK_OT_cancel_remove,
    MIXAR_BYOK_OT_confirm_remove,
)
