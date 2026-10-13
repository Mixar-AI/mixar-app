# SPDX-FileCopyrightText: 2026 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""BYOK operators: dialog + save/remove actions.

State machine lives on WindowManager (see ui/properties/byok_props.py).
The dialog operator's draw() delegates to `byok_dialog_ui.draw_dialog`,
which dispatches on `wm.byok_dialog_state` (IDLE / SAVING / REMOVING /
SAVED / REMOVED / ERROR) and renders with the profile
card's design system. Save and Remove spawn async work through
`core/byok_client.py`; callbacks mutate WM state on the main thread and
the props dialog redraws on the next tick.

The dialog draws its own single-primary-action footer and always marks
one button active-default, which suppresses the props dialog's automatic
OK/Cancel row (`wm_block_dialog_create` skips it when the block already
has a default button) — the redundant Save-plus-OK pair is gone. Success
lands on an explicit SAVED / REMOVED recap with one Done button, so
"did it save?" is never a question.
"""

import bpy
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_

from ...constants import PROVIDER_DIALOG_WIDTH
from ...core import byok_client, credential_state, model_suggestions, models_cache
from ...core import preference_state
from . import byok_dialog_host, byok_dialog_refresh, byok_dialog_ui
from .byok_state_ops import (
    _apply_cached_state,
    _redraw_mixie_chat_areas,
)

logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _wipe_form_secrets(wm):
    """Remove transient API/token material from the live WindowManager."""
    for attr in (
        'byok_form_api_key',
        'byok_form_codex_bundle',
        'byok_form_local_custom_key',
    ):
        try:
            setattr(wm, attr, '')
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Dialog entry point
# ---------------------------------------------------------------------------

# True while the props dialog is on screen. Re-invoking would stack another
# dialog (and reset the form state under the one already open), so invoke()
# refuses while set; execute()/cancel() clear it when the dialog closes.
_dialog_open = False


def _account_busy() -> bool:
    """Another change of the key or the pick is in flight: an island toggle /
    model switch, a save / removal sent from a dialog closed mid-request, or a
    hosted pick (whose echo / revert would put the old byok_active back over
    this save's). One at a time, so no late answer undoes another."""
    return (credential_state.pending() or byok_client.mutation_in_flight()
            or preference_state.mutation_pending())


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
        # lands. Never prefill the api_key field.
        # (The dialog can be closed with Esc mid-request; only the ✕ hides.)
        if not byok_client.mutation_in_flight():
            wm.byok_dialog_state = 'IDLE'
            wm.byok_last_error = ''
        _wipe_form_secrets(wm)  # never prefill credential material
        # If a key is stored (in use or paused), prefill provider/model so
        # the user sees what's currently saved and can edit from there.
        # Provider assignment can fail if the cache hasn't been populated
        # yet (the saved provider isn't in the current EnumProperty items)
        # — guard against TypeError.
        if wm.byok_is_active or wm.byok_key_stored:
            if wm.byok_current_provider:
                try:
                    wm.byok_form_provider = wm.byok_current_provider
                except TypeError:
                    logger.debug(
                        "Could not prefill provider %s — not in cache yet",
                        wm.byok_current_provider,
                    )
            if model_suggestions.is_openrouter(wm.byok_current_provider):
                # OpenRouter uses a free-text model slug, not the catalog dropdown.
                if wm.byok_current_model:
                    wm.byok_form_openrouter_model = wm.byok_current_model
            elif model_suggestions.is_local(wm.byok_current_provider):
                pass  # prefilled below by byok_local_ops.prepare_dialog
            elif wm.byok_current_model:
                try:
                    wm.byok_form_model = wm.byok_current_model
                except TypeError:
                    logger.debug(
                        "Could not prefill model %s — not in cache for this provider",
                        wm.byok_current_model,
                    )
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
        # A props dialog (not invoke_popup) so the dialog redraws through
        # SAVING → IDLE / ERROR without user interaction. byok_dialog_host
        # hosts it in the main window, centred, with the always-on-top
        # island minimised while it is up (restored on close).
        _dialog_open = True
        try:
            return byok_dialog_host.open_dialog(context, self, PROVIDER_DIALOG_WIDTH)
        except Exception:
            _dialog_open = False
            raise

    def execute(self, context):
        global _dialog_open
        _dialog_open = False
        byok_dialog_refresh.forget()
        byok_dialog_host.dialog_closed()
        # No-op: Save / Remove are their own operators, invoked from draw().
        _wipe_form_secrets(context.window_manager)
        return {'FINISHED'}

    def cancel(self, context):
        """Esc/click-away must not leave JWTs or API keys in RNA memory."""
        global _dialog_open
        _dialog_open = False
        byok_dialog_refresh.forget()
        byok_dialog_host.dialog_closed()
        _wipe_form_secrets(context.window_manager)

    def draw(self, context):
        byok_dialog_refresh.remember(getattr(context, "region_popup", None))
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
        # button has no disabled look to lean on).
        # The island's toggle / model switch is a mutation of the same key:
        # one at a time, or a late echo would resurrect what this changes.
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

        if (
            provider == 'NONE'
            or not model_suggestions.is_valid_model(provider, model)
            or not api_key
        ):
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = n_("Choose a model for this provider and enter an API key.")
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

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
            wm.byok_last_error = n_("Model slug and API key are required.")
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

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
        """Codex save: send the pasted auth.json bundle as the credential. The
        backend refreshes the token (validating it) and stores the bundle.
        The model is the shared catalog dropdown, fed by the "openai" group."""
        model = wm.byok_form_model
        bundle = wm.byok_form_codex_bundle.strip()
        if not model_suggestions.is_valid_model('codex', model) or not bundle:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = n_("Choose a Codex model and load your auth.json bundle.")
            return {'CANCELLED'}

        wm.byok_dialog_state = 'SAVING'
        wm.byok_last_error = ''
        _redraw_mixie_chat_areas()

        byok_client.save_credentials(
            provider='codex',
            model=model,
            api_key=bundle,
            on_done=_save_callback(),
        )
        return {'FINISHED'}


def _deregister_local_if_switched_away(active_provider):
    """The credential set now points at ``active_provider`` (None = removed).
    If a managed local registration is still on disk, tear it down — the
    backend will never relay to it again, so keeping llama-server running
    (and resurrecting it every startup) would waste the user's RAM.
    Main thread."""
    try:
        from mixar.modules.byok.constants import LOCAL_PROVIDER_ID
        if active_provider == LOCAL_PROVIDER_ID:
            return
        from mixar.modules.local_models.core import manifest, orchestrator
        if manifest.get_registered() is None:
            return
        logger.info("BYOK switched off local — deregistering local runtime")
        orchestrator.deregister()
    except Exception as e:
        logger.warning("Local deregistration skipped: %s", e)


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
        else:
            if epoch is not None and epoch != credential_state.current_epoch():
                wm.byok_dialog_state = 'IDLE'
                return  # another account by now; nothing of this save remains
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or n_("Save failed.")
            logger.warning("BYOK save failed: %s", err)
            _toast_if_closed(n_("Couldn't save your API key"), err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK save callback failed: %s", e, exc_info=True)


def _toast_if_closed(title, err):
    """A request whose dialog was closed (Esc) still owes the user its
    failure; an open dialog shows it inline."""
    if _dialog_open:
        return
    try:
        from mixar.modules.common.notifications import get_notification_store

        get_notification_store().push(
            "error", title, body=err or n_("Please try again."), ttl_ms=8000,
            id="byok_request_failed",
        )
    except Exception:  # noqa: BLE001 — the log line already records it
        pass


# ---------------------------------------------------------------------------
# Remove (one click: closing the dialog afterwards never keeps the key)
# ---------------------------------------------------------------------------

class MIXAR_BYOK_OT_confirm_remove(Operator):
    """Delete your saved API key. The agent goes back to Mixie"""
    bl_idname = "mixar_byok.confirm_remove"
    bl_label = "Remove API Key"
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
            # Nothing stored any more — without bumping the logout epoch (a
            # save made right after must keep its echo). Mixie answers now:
            # every row is gone, so byok_active is false by construction;
            # move the island at once and let the refresh confirm.
            credential_state.apply_removed(wm)
            _wipe_form_secrets(wm)
            preference_state.invalidate_reads()
            preference_state.apply_local({'mixar_agent_model_byok_active': False}, wm)
            preference_state.refresh()
            # REMOVED, not IDLE — explicit recap, same as the save path.
            wm.byok_dialog_state = 'REMOVED'
            wm.byok_last_error = ''
            logger.info("BYOK removed: %d row(s) deleted", removed_count)
            _deregister_local_if_switched_away(None)
        else:
            wm.byok_dialog_state = 'ERROR'
            wm.byok_last_error = err or n_("Remove failed.")
            logger.warning("BYOK remove failed: %s", err)
            _toast_if_closed(n_("Couldn't remove your API key"), err)
        _redraw_mixie_chat_areas()
    except Exception as e:
        logger.error("BYOK delete callback failed: %s", e, exc_info=True)


# ---------------------------------------------------------------------------
# Registration (picked up by bootstrap auto-discovery)
# ---------------------------------------------------------------------------
# The fetch operators (mixar_byok.fetch_state / fetch_models_catalog)
# and the cached-state mirror live in byok_state_ops.py.

classes = (
    MIXAR_BYOK_OT_open_dialog,
    MIXAR_BYOK_OT_save,
    MIXAR_BYOK_OT_confirm_remove,
)
