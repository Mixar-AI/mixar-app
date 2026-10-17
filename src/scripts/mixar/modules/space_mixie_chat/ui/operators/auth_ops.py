# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication operators for Mixie Chat.

Provides operators for user login and logout functionality.
"""

import threading
import time

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from mixar.config.logging_config import get_logger
from mixar.modules.common.i18n import n_, rpt_
from mixar.modules.common.utils.app_activate import activate_app
from mixar.modules.common.utils.sign_in import (
    begin_sign_in,
    finish_sign_in,
    is_current_sign_in,
    redraw_sign_in_surfaces,
    sync_pending_flag,
)

from ....auth.core.auth import (
    clear_credentials,
    get_access_token,
    get_user_info,
    open_dashboard_with_handoff,
    refresh_access_token,
)
from ....auth.core import guest
from ....auth.core.auth_hooks import (
    invalidate_agent_settings,
    invalidate_generation_caches,
    maybe_show_onboarding,
    refresh_agent_settings,
    refresh_generation_caches,
)
from ....auth.core.sso import sso_login
from ....auth.utils.constants import SSO_LOGIN_TIMEOUT_S

logger = get_logger(__name__)


_auto_connect_scheduled = False


def _capture_session_started(method: str, refreshed=None) -> None:
    """Telemetry only — auth must never break because of it."""
    try:
        from mixar.modules.common.analytics.session_events import (
            capture_session_started,
        )
        capture_session_started(
            method, refreshed=refreshed, context=bpy.context,
        )
    except Exception as exc:
        logger.debug("session_started capture failed: %s", exc)


def _auto_connect_websocket():
    """Connect WebSocket after login (with small delay to ensure UI is ready).

    Uses ConnectionManager directly instead of bpy.ops to avoid
    context/poll issues when called from timer callbacks.
    """
    global _auto_connect_scheduled
    if _auto_connect_scheduled:
        logger.debug("Auto-connect already scheduled, skipping duplicate")
        return
    _auto_connect_scheduled = True

    def _delayed_connect():
        global _auto_connect_scheduled
        try:
            from ...core.connection_manager import get_connection_manager
            manager = get_connection_manager()
            logger.info("Auto-connect: is_connected=%s, initiating connection...", manager.is_connected)
            if not manager.is_connected:
                manager.initialize()
                result = manager.connect()
                logger.info("Auto-connect: connect() returned %s", result)
                if result:
                    # Schedule a safety check: if still CONNECTING after 15s, reset.
                    bpy.app.timers.register(_connecting_timeout_check, first_interval=15.0)
                else:
                    _auto_connect_scheduled = False
            else:
                # WebSocket survived the file load but new scenes default to
                # OFFLINE.  Sync all scenes to IDLE so the bubble shows the
                # correct "Idle" status instead of "Disconnected".
                logger.info("Auto-connect: already connected, syncing scene state")
                from ...core.session import get_session_manager
                from ...constants import SessionState
                session = get_session_manager()
                session.set_all_scenes_state(
                    SessionState.IDLE,
                    only_from={SessionState.OFFLINE, SessionState.CONNECTING},
                )
        except Exception as e:
            logger.warning("Auto-connect failed: %s", e)
            _auto_connect_scheduled = False
        return None  # Don't repeat

    bpy.app.timers.register(_delayed_connect, first_interval=0.5)


def _connecting_timeout_check():
    """Reset CONNECTING state to OFFLINE if WS hasn't connected within timeout."""
    global _auto_connect_scheduled
    try:
        from ...core.jsonrpc_client import cleanup_jsonrpc_client
        from ...core.session import get_session_manager
        from ...constants import SessionState
        session = get_session_manager()
        import bpy
        for scene in bpy.data.scenes:
            if session.get_state(scene) == SessionState.CONNECTING:
                logger.warning("Connection timed out — resetting to OFFLINE")
                cleanup_jsonrpc_client()
                session.set_all_scenes_state(SessionState.OFFLINE)
                break
    except Exception as e:
        logger.debug("Connecting timeout check failed: %s", e)
    _auto_connect_scheduled = False  # always clear
    return None  # Don't repeat


def _apply_account_name(user_info) -> None:
    """Store the profile card's greeting name from a ``/me`` payload.

    The card is drawn in C++ and reads `wm.mixar_account_name`; deriving
    it here (rather than in the draw) keeps the string work off every
    redraw and out of the native layer.
    """
    try:
        from mixar.modules.common.usage.core import account

        account.apply_from_user_info(user_info)
    except Exception as exc:  # noqa: BLE001 — greeting must not break login
        logger.debug("Account name apply failed: %s", exc)


def _clear_account_name() -> None:
    """Drop the greeting name so the next user isn't greeted by this one's."""
    try:
        from mixar.modules.common.usage.core import account, poller

        account.clear()
        poller.on_logout()
    except Exception as exc:  # noqa: BLE001
        logger.debug("Account name clear failed: %s", exc)


def _clear_byok_state_on_logout(wm):
    """Reset cached BYOK state + form fields + models-catalog cache.

    Done inline (not via operator) because logout is synchronous and we
    want the gear icon to update on the same redraw pass.
    """
    for attr, default in (
        ('byok_is_active', False),
        ('byok_current_provider', ''),
        ('byok_current_model', ''),
        ('byok_current_supports_vision', True),
        ('byok_key_preview', ''),
        ('byok_device_key_missing', False),
        ('byok_key_resumable', False),
        ('byok_form_api_key', ''),
        ('byok_form_openrouter_model', ''),
        ('byok_form_codex_path', ''),
        ('byok_form_local_custom_base', ''),
        ('byok_form_local_custom_model', ''),
        ('byok_form_local_custom_key', ''),
        ('byok_dialog_state', 'IDLE'),
        ('byok_last_error', ''),
    ):
        if hasattr(wm, attr):
            try:
                setattr(wm, attr, default)
            except Exception as e:
                logger.debug("Failed clearing %s on logout: %s", attr, e)

    # NOTE: the models-catalog cache is NOT cleared here. `invalidate_agent_settings()`
    # owns it, and clears memory, suggestions and the disk file together under the
    # cache's epoch bump. Doing it from two places gave a worker still in flight two
    # orderings to win in — which is the race this whole change removes.

    # Local provider: stop the managed llama-server and drop transient
    # relay grants + UI mirrors. Downloaded model files stay on disk.
    try:
        from mixar.modules.local_models.core import orchestrator
        orchestrator.on_logout()
    except Exception as e:
        logger.debug("Failed stopping local model server on logout: %s", e)
    try:
        from mixar.modules.byok.core import local_provider
        local_provider.clear()
    except Exception as e:
        logger.debug("Failed clearing local provider caches on logout: %s", e)
    try:
        from mixar.modules.local_models.ui.properties.local_models_props import (
            wipe_transient_state,
        )
        wipe_transient_state(wm)
    except Exception as e:
        logger.debug("Failed clearing local model mirrors on logout: %s", e)


def _clear_referral_state(wm):
    """Drop the session-cached Refer a Friend link (logout and every SSO
    login) so another account never opens the dialog on this one's link."""
    try:
        from mixar.modules.referrals.core import flow as referral_flow
        referral_flow.clear(wm)
    except Exception as e:  # noqa: BLE001 — stripped builds lack the module
        logger.debug("Failed clearing referral state: %s", e)


def _drop_foreign_chats(address: str, is_guest: bool) -> None:
    """A chat belongs to the identity that started it: the backend refuses
    another identity's continued session ("Session unavailable"). Sign-out
    starts a fresh chat in every tab, but an identity can change without one
    (a guest whose token was lost is issued a fresh guest). Every open tab
    whose chat another identity started starts a fresh one, archived under
    that identity. Only a claim (this guest signing in to an account) keeps
    its chats: the claim moved their ownership to the account."""
    claimed_from = guest.email() if guest.is_guest() and not is_guest else ""
    from .session_ops import start_new_chat
    for open_scene in bpy.data.scenes:
        owner = getattr(open_scene, "mixie_chat_user_id", "") or ""
        if (not owner or owner in (address, claimed_from)
                or not getattr(open_scene, "mixie_session_id", "")):
            continue
        try:
            start_new_chat(open_scene)
        except Exception as e:  # noqa: BLE001 — never block a sign-in
            logger.warning("Fresh chat for %r after an identity change failed: %s",
                           open_scene.name, e)


def _apply_identity(wm, scene, user_info: dict) -> bool:
    """Mirror a ``/me`` payload onto the session; True for a guest.

    One place for every login apply path: the account props, the greeting
    name and the guest flag (``wm.mixie_chat_is_guest`` + the auth module's
    marker) always change together.
    """
    data = user_info["data"]
    email = data.get("email", "")
    is_guest = bool(data.get("is_guest", False))
    _drop_foreign_chats(email, is_guest)
    if scene is not None:
        scene.mixie_chat_user_id = email
        scene.mixie_chat_credits = data.get("credits", 0)
    if hasattr(wm, 'mixie_chat_is_guest'):
        wm.mixie_chat_is_guest = is_guest
    guest.mark(is_guest, email)
    _apply_account_name(user_info)
    # The account lane is a global-area header: nothing else repaints it
    # when the session flips between guest and account.
    from ....common.updates.core.toasts import tag_topbar_redraw
    tag_topbar_redraw()
    return is_guest


def _apply_account_hooks(user_info: dict, is_guest: bool) -> None:
    """The post-login fetches. Routes a guest cannot call (the generation
    catalog, sounds, telemetry) are skipped rather than answered 403; the
    agent settings are a guest's own (its key, the catalog, its pick).
    Onboarding is per device, so a guest's first launch gets the tour."""
    if not is_guest:
        refresh_generation_caches()
    maybe_show_onboarding(user_info["data"].get("email", ""))
    _auto_connect_websocket()
    refresh_agent_settings()


def _leave_guest_session() -> None:
    """Switch the live session from the guest to the account that signed in.

    The guest socket is closed cleanly (a dropped socket holds the instance id
    for up to 60 s and the account's reconnect would see 4009) and its cached
    agent settings dropped — whether or not the claim went through; what the
    guest owned moves only with a claim (``_apply_guest_claim``). Main thread,
    before the account's identity is applied.
    """
    global _auto_connect_scheduled
    from ...core import get_connection_manager
    get_connection_manager().disconnect()
    _auto_connect_scheduled = False
    invalidate_agent_settings()


def _apply_guest_claim(claim: dict, account_email: str) -> None:
    """Main thread: move a CLAIMED guest's device state to the account.

    The one post-claim step for a sign-in that claimed the guest directly
    (``guest.sign_in``) and for a claim retried after a transient failure
    (``guest.retry_pending_claim``). The backend moved the guest's BYOK row,
    so the key material for it — on this device, keyed by user id — is
    re-scoped too (the account's own record wins), or the first turn would
    report the device key missing; the guest's chat archive is re-filed under
    the account. Callers run ``_apply_account_hooks`` right after, whose
    ``refresh_agent_settings`` reloads the BYOK state. Nothing happens for a
    claim that did not succeed: the guest's key and chats stay its own.
    """
    if not (claim and claim.get("claimed_guest")):
        return
    if claim.get("byok_moved") and claim.get("guest_user_id"):
        try:
            from mixar.modules.byok.core import key_store
            key_store.reassign(claim["guest_user_id"], key_store.current_user_id())
        except Exception as e:  # noqa: BLE001 — the user can re-add the key
            logger.warning("Guest BYOK device key carry-over failed: %s", e)
    try:
        from ...core import chat_history
        chat_history.reassign_owner(claim.get("guest_email", ""), account_email)
    except Exception as e:  # noqa: BLE001 — history is best-effort
        logger.debug("Guest chat history reassign failed: %s", e)


def _schedule_apply_login(user_info: dict, refreshed: bool) -> None:
    """Schedule main-thread bpy property updates after successful auth.

    Called from a daemon thread — uses bpy.app.timers (thread-safe) to
    write bpy properties back on the main thread. A validated account first
    retries a guest claim that failed transiently at its sign-in.
    """
    claim = {} if user_info["data"].get("is_guest") else guest.retry_pending_claim()

    def _apply() -> None:
        global _auth_check_started
        try:
            wm = bpy.context.window_manager
            scene = bpy.context.scene
            wm.mixie_chat_is_logged_in = True
            if hasattr(wm, 'mixie_chat_session_expired'):
                wm.mixie_chat_session_expired = False
            wm.mixie_chat_login_error = ""
            is_guest = _apply_identity(wm, scene, user_info)
            _apply_guest_claim(claim, user_info["data"].get("email", ""))
            if refreshed:
                logger.info("Token refreshed successfully on startup")
            if not is_guest:
                _capture_session_started("startup_token", refreshed=refreshed)
            _apply_account_hooks(user_info, is_guest)
        except Exception as e:
            logger.warning("Auth state apply failed: %s", e)
        finally:
            _auth_check_started = False
        return None  # Don't repeat

    bpy.app.timers.register(_apply, first_interval=0.0)


def _stay_signed_out() -> None:
    """Guest fallback after a sign-out: nothing to do but release the latch."""
    global _auth_check_started
    _auth_check_started = False


# A socket whose auth backoff gave up hands the session back here; two of
# those inside this window are one event (the backend is still refusing).
_RECOVERY_MIN_GAP_S = 30.0
_last_recovery = 0.0


def recover_session() -> None:
    """The socket's credentials are gone for good: its auth backoff stopped
    because a refresh was rejected, or no pair is left (the kill switch
    flipped, the token was revoked or rotated by another process, the guest
    was claimed elsewhere). Nothing else would run the auth check again, so
    the app sat OFFLINE as a token-less "guest" until a relaunch.

    Any thread. Re-runs the startup check on the main thread: a pair that is
    still here is validated or refreshed and the socket reconnects; a dead
    guest pair becomes a fresh guest (the same silent replacement a relaunch
    does); a dead account pair gets the session-expired sign-in.
    """
    global _last_recovery
    now = time.monotonic()
    if now - _last_recovery < _RECOVERY_MIN_GAP_S:
        logger.info("Session recovery skipped: one ran %.0fs ago", now - _last_recovery)
        return
    _last_recovery = now

    def _start():
        global _auth_check_started, _auto_connect_scheduled
        if _auth_check_started:
            logger.info("Session recovery skipped: an auth check is running")
            return None
        _auth_check_started = True
        _auto_connect_scheduled = False
        threading.Thread(
            target=_recover_session_background, daemon=True, name="MixarAuthRecover",
        ).start()
        return None

    bpy.app.timers.register(_start, first_interval=0.0)


def _recover_session_background() -> None:
    """Daemon thread body of ``recover_session``."""
    try:
        if get_access_token():
            # The pair survived (only the socket's copy was refused): the
            # ordinary check validates or refreshes it and reconnects.
            _auth_check_background()
            return
        if guest.is_guest():
            logger.info("Guest pair gone while running; starting a fresh guest")
            _enter_guest_session(fallback=_reauthenticate)
            return
        logger.info("Account pair gone while running; session expired")
        _reauthenticate()
    except Exception as e:  # noqa: BLE001 — never leave the latch set
        global _auth_check_started
        logger.warning("Session recovery failed: %s", e)
        _auth_check_started = False


def _enter_guest_session(fallback) -> None:
    """Daemon thread: start a fresh guest session, else run ``fallback``.

    ``fallback`` is the caller's signed-out behaviour — the browser sign-in
    at startup, nothing after a sign-out — for a backend whose guest kill
    switch is off or that cannot be reached.
    """
    global _auth_check_started
    result = guest.create_guest_session()
    if result.get("success"):
        user_info = get_user_info()
        if user_info and user_info.get("status") == "success":
            _schedule_apply_login(user_info, refreshed=False)
            return
        logger.warning("Guest session issued but /me failed; keeping its tokens")
        _auth_check_started = False
        return
    logger.info("No guest session (%s); signed-out behaviour", result.get("message"))
    fallback()


def _auth_check_background() -> None:
    """Validate/refresh the stored token on a daemon thread.

    All HTTP I/O (get_user_info, refresh_access_token) happens here.
    bpy property writes are handed back to the main thread via a timer.
    """
    global _auth_check_started
    user_info = get_user_info()
    if user_info is None:
        # No stored pair: a guest session, or the browser sign-in when the
        # backend does not issue guests.
        _enter_guest_session(fallback=_reauthenticate)
        return
    if user_info.get("status") == "success":
        _schedule_apply_login(user_info, refreshed=False)
        return

    # Token invalid — try refresh. Snapshot the access token first so a
    # definitive rejection can distinguish "this pair is dead" from "another
    # Blender process rotated the pair while our request was in flight".
    logger.debug("Access token invalid, attempting refresh")
    stale_access_token = get_access_token()
    refresh_result = refresh_access_token()

    if refresh_result and refresh_result.get("success"):
        user_info = get_user_info()
        if user_info and user_info.get("status") == "success":
            _schedule_apply_login(user_info, refreshed=True)
            return
        # Rotation succeeded, so the new credential pair is authoritative.
        # A transient /me failure must not delete it and launch SSO.
        logger.warning("Post-refresh user validation failed; preserving credentials")
        _auth_check_started = False
        return

    if refresh_result and refresh_result.get("retryable"):
        # The refresh attempt is deliberately retained with its idempotency key
        # for a later check. Clearing credentials here would destroy recovery
        # after a timeout, proxy error, rate limit, or backend outage.
        logger.warning(
            "Token refresh failed transiently; preserving credentials for retry: %s",
            refresh_result.get("message"),
        )
        _auth_check_started = False
        return

    # A definitive rejection can also mean a second Blender process won the
    # rotation race: its refresh consumed the token first, and the 401 handler
    # deliberately leaves that foreign pair in safe storage. If the stored
    # access token changed to a different non-empty value, that pair is
    # authoritative — adopt it rather than destroying it. (Our own definitive
    # 401 deletes the pair, leaving it empty, so this never masks a real
    # rejection.)
    current_access_token = get_access_token()
    if current_access_token and current_access_token != stale_access_token:
        user_info = get_user_info()
        if user_info and user_info.get("status") == "success":
            _schedule_apply_login(user_info, refreshed=True)
            return
        logger.warning(
            "Refresh rejected but another process stored newer credentials; "
            "preserving them"
        )
        _auth_check_started = False
        return

    # A definitive 401/403 requires reauthentication.
    logger.info("Token refresh was definitively rejected, clearing credentials")
    clear_credentials()
    if guest.stored_pair_is_guest():
        # A guest pair that died (idle sweep, kill-switch flip) is replaced
        # by a fresh guest; only an account gets the "session expired" flow.
        _enter_guest_session(fallback=_reauthenticate)
        return
    _reauthenticate()



def _reauthenticate() -> None:
    """Daemon thread: the signed-out flow — mark the session expired and run
    the browser sign-in (the pair is already gone)."""
    global _auth_check_started
    # Reserve the one in-flight sign-in BEFORE the browser opens: the bubble
    # autoshow gate reads the reservation itself (common/utils/sign_in.py),
    # so no main-thread round trip is needed. A sign-in the user already
    # started owns the browser — never open a second one on our own.
    attempt = begin_sign_in(supersede=False)
    sso_thread = threading.current_thread()

    def _mark_expired():
        wm = getattr(bpy.context, 'window_manager', None)
        if wm:
            if hasattr(wm, 'mixie_chat_session_expired'):
                wm.mixie_chat_session_expired = True
            if attempt is not None and hasattr(wm, 'mixie_chat_login_error'):
                wm.mixie_chat_login_error = ""
            if hasattr(wm, 'mixie_chat_is_guest'):
                wm.mixie_chat_is_guest = False
            sync_pending_flag(wm)
            redraw_sign_in_surfaces(wm)
        guest.mark(False)
        if attempt is not None:
            _arm_login_watchdog(attempt[0], sso_thread)
        return None

    bpy.app.timers.register(_mark_expired, first_interval=0.0)
    if attempt is None:
        logger.info("Session expired while a browser sign-in is already open; not opening another")
        _auth_check_started = False
        return
    attempt_id, cancel = attempt

    try:
        # Run SSO on this same background thread (it blocks waiting for
        # browser); guest.sign_in claims the guest this sign-in replaces.
        try:
            result = guest.sign_in(lambda: sso_login(cancel=cancel))
        except Exception as e:
            logger.error("Auto SSO login failed: %s", e)
            result = {"success": False, "message": str(e)}

        # Fetch user info on this background thread (not on main thread)
        user_info = _user_info_after_sso(result)
    except BaseException:
        # Never leave this attempt holding the sign-in UI and the autoshow.
        finish_sign_in(attempt_id, cancel=True)
        bpy.app.timers.register(_sync_pending_flag_timer, first_interval=0.0)
        raise

    def _apply_sso_result():
        global _auth_check_started
        current = finish_sign_in(attempt_id)
        wm = getattr(bpy.context, 'window_manager', None)
        if not wm:
            _auth_check_started = False
            return None
        try:
            sync_pending_flag(wm)

            if not result.get("success") and not current:
                # Replaced by a newer sign-in (or released by the watchdog):
                # that attempt owns the UI now.
                logger.info("Superseded auto sign-in %s ended: %s", attempt_id, result.get('message'))
            elif result.get("success"):
                wm.mixie_chat_is_logged_in = True
                if hasattr(wm, 'mixie_chat_session_expired'):
                    wm.mixie_chat_session_expired = False
                wm.mixie_chat_login_error = ""
                # The user just finished in the browser: land them back in
                # Mixar. Success only — a cancelled login must not steal focus.
                activate_app()

                _clear_referral_state(wm)

                if user_info and user_info.get("status") == "success":
                    if result.get("switched_from_guest"):
                        _leave_guest_session()
                    is_guest = _apply_identity(wm, bpy.context.scene, user_info)
                    _apply_guest_claim(result, user_info["data"].get("email", ""))
                    _apply_account_hooks(user_info, is_guest)
                    logger.info("Auto SSO re-login completed successfully")
                # After the identity: capture() drops a guest's events, and
                # the once-guard would be spent on the dropped one.
                if not guest.is_guest():
                    _capture_session_started("sso_relogin")
            else:
                if hasattr(wm, 'mixie_chat_login_error'):
                    # Keep the real reason: a classified network failure
                    # (support code included) is what the customer quotes.
                    reason = result.get('message') or rpt_("Please log in again.")
                    wm.mixie_chat_login_error = rpt_("Session expired. {reason}").format(reason=reason)
                logger.warning("Auto SSO re-login failed: %s", result.get('message'))
        except Exception as e:
            logger.warning("SSO result apply failed: %s", e)
        finally:
            _auth_check_started = False
            redraw_sign_in_surfaces(wm)
        return None

    bpy.app.timers.register(_apply_sso_result, first_interval=0.0)


_auth_check_started = False


def _user_info_after_sso(result: dict):
    """``/me`` after a successful SSO, on the calling (background) thread.

    Never raises: the caller must always reach the main-thread apply that
    clears the pending flag, whatever the profile fetch did.
    """
    if not result.get("success"):
        return None
    if "claimed_guest" not in result:
        # This sign-in claimed nothing itself: an earlier claim that failed
        # transiently is retried under the account it was made for.
        result.update(guest.retry_pending_claim())
    try:
        return get_user_info()
    except Exception as e:  # noqa: BLE001
        logger.warning("User info fetch after SSO failed: %s", e)
        return None


def _sync_pending_flag_timer():
    """Main-thread mirror of the sign-in registry onto the UI flag."""
    sync_pending_flag(getattr(bpy.context, 'window_manager', None))
    return None


def _auth_check_background_safe() -> None:
    """Run auth check and release the startup latch if it crashes early."""
    global _auth_check_started
    try:
        _auth_check_background()
    except Exception as e:
        logger.error("Auth check failed before scheduling a UI result: %s", e, exc_info=True)
        _auth_check_started = False


@persistent
def check_auth_on_startup(_):
    """Check if stored auth token is valid on app startup.

    Runs only the minimum on the main thread (property existence check +
    keyring read), then hands all HTTP work to a daemon thread so the
    main thread is never blocked waiting for network I/O.
    """
    global _auth_check_started, _auto_connect_scheduled

    # Guard: context or properties may not be available during deferred startup
    wm = getattr(bpy.context, 'window_manager', None)
    if not wm or not hasattr(wm, 'mixie_chat_is_logged_in'):
        logger.debug("Auth check skipped: WindowManager properties not registered yet")
        return

    # Prevent duplicate auth checks while one is already running (timer +
    # load_post can both fire on startup). The flag is cleared when the
    # background result is applied, so later file loads can hydrate the new
    # active scene.
    if _auth_check_started:
        logger.info("Auth check already in progress, skipping duplicate (caller=%s)", _)
        return
    _auth_check_started = True

    # Reset the auto-connect guard so the upcoming auth → connect flow can
    # actually trigger a new connection (or scene-state sync) for this file.
    # The previous _delayed_connect timer has already completed by now.
    _auto_connect_scheduled = False

    logger.info("Starting auth check (caller=%s)", _)

    # Hand off all HTTP work to a daemon thread; bpy updates come back
    # via a timer scheduled inside _auth_check_background().
    # When no token is stored, _auth_check_background fast-fails the
    # validation steps (no HTTP requests) and falls through to SSO.
    threading.Thread(
        target=_auth_check_background_safe,
        daemon=True,
        name="MixarAuthCheck",
    ).start()


# Grace added to the SSO timeout before the UI watchdog gives up on a login
# thread that never reported back.
_LOGIN_WATCHDOG_GRACE_S = 30


def _release_stuck_login(attempt_id, thread):
    """Timer: clear "Waiting for browser..." if the SSO thread is still running.

    The SSO flow has its own deadline, so this only fires if something below
    it wedged (it did once: a silent peer on the callback socket). Scoped to
    one attempt so a stale timer can never clobber a newer login.
    """
    if not is_current_sign_in(attempt_id) or not thread.is_alive():
        return None
    if not finish_sign_in(attempt_id, cancel=True):
        return None
    logger.error(
        "SSO login thread still running %ss after its deadline; releasing the UI",
        SSO_LOGIN_TIMEOUT_S + _LOGIN_WATCHDOG_GRACE_S,
    )
    try:
        wm = bpy.context.window_manager
        sync_pending_flag(wm)
        wm.mixie_chat_login_error = rpt_(
            "Browser login did not complete. Please try again."
        )
        redraw_sign_in_surfaces(wm)
    except Exception as e:
        logger.warning("Login watchdog could not update UI: %s", e)
    return None


def _arm_login_watchdog(attempt_id, sso_thread) -> None:
    """Both sign-in paths (auto SSO and the button) release the UI through
    the same scoped watchdog; the pending flag must never outlive a login."""
    bpy.app.timers.register(
        lambda: _release_stuck_login(attempt_id, sso_thread),
        first_interval=SSO_LOGIN_TIMEOUT_S + _LOGIN_WATCHDOG_GRACE_S,
    )


class MIXIE_CHAT_OT_login(Operator):
    """Login to Mixie Chat via browser SSO"""
    bl_idname = "mixie_chat.login"
    bl_label = "Login"
    bl_description = "Login to Mixie Chat via browser SSO"

    def execute(self, context):
        wm = context.window_manager
        # Supersede: a click while a sign-in is pending (the user closed the
        # browser tab, or a startup sign-in is open) cancels it and starts
        # again, so the button is never a dead end.
        attempt_id, cancel = begin_sign_in(supersede=True)

        # Set loading state and force redraw.
        sync_pending_flag(wm)
        wm.mixie_chat_login_error = ""
        redraw_sign_in_surfaces(wm)

        # Run SSO on a background thread (blocks waiting for browser callback)
        def _sso_thread():
            try:
                # Claims the guest this sign-in replaces (guest.sign_in).
                result = guest.sign_in(lambda: sso_login(cancel=cancel))
                logger.info("SSO login returned: success=%s", result.get("success"))
            except Exception as e:
                logger.error("SSO login failed with exception: %s", e)
                result = {"success": False, "message": str(e)}

            # Fetch user info on this background thread (not on main thread)
            user_info = _user_info_after_sso(result)

            def _apply_result():
                current = finish_sign_in(attempt_id)
                try:
                    live_wm = bpy.context.window_manager
                    sync_pending_flag(live_wm)

                    if not result["success"] and not current:
                        # Replaced by a newer sign-in (or released by the
                        # watchdog): that attempt owns the UI now.
                        logger.info("Superseded sign-in %s ended: %s",
                                    attempt_id, result.get("message"))
                    elif result["success"]:
                        live_wm.mixie_chat_login_error = ""
                        live_wm.mixie_chat_is_logged_in = True
                        if hasattr(live_wm, 'mixie_chat_session_expired'):
                            live_wm.mixie_chat_session_expired = False
                        # Land the user back in Mixar from the browser.
                        # Success only — never on a failed or cancelled login.
                        activate_app()
                        _clear_referral_state(live_wm)

                        if user_info and user_info.get("status") == "success":
                            if result.get("switched_from_guest"):
                                _leave_guest_session()
                            is_guest = _apply_identity(live_wm, bpy.context.scene, user_info)
                            _apply_guest_claim(result, user_info["data"].get("email", ""))
                            _apply_account_hooks(user_info, is_guest)
                            logger.info("SSO login completed — user is logged in")
                        # After the identity (guest.mark(False)): capture()
                        # drops a guest's events and the once-guard would be
                        # spent on the dropped one.
                        if not guest.is_guest():
                            _capture_session_started("interactive_login")
                    else:
                        msg = result.get("message", rpt_("Login failed"))
                        live_wm.mixie_chat_login_error = msg
                        logger.warning("SSO login failed: %s", msg)

                    # Redraw every surface that shows the auth state
                    redraw_sign_in_surfaces(live_wm)
                except Exception as e:
                    logger.error("SSO result apply failed: %s", e)
                return None  # Don't repeat

            bpy.app.timers.register(_apply_result, first_interval=0.0)

        sso_thread = threading.Thread(
            target=_sso_thread, daemon=True, name="MixarSSOLogin"
        )
        sso_thread.start()
        _arm_login_watchdog(attempt_id, sso_thread)
        return {'FINISHED'}


class MIXIE_CHAT_OT_logout(Operator):
    """Logout from Mixie Chat"""
    bl_idname = "mixie_chat.logout"
    bl_label = "Logout"
    bl_description = "Logout from Mixie Chat"

    def execute(self, context):
        global _auth_check_started, _auto_connect_scheduled
        scene = context.scene
        wm = context.window_manager

        # Every open chat belongs to the account that is leaving; the next
        # seat (a fresh guest, or nobody) owns none of them and the backend
        # refuses a continued session it does not own (-32013). Each tab
        # starts a fresh chat, archived under the account first — History
        # reads scene.mixie_chat_user_id, which is cleared below.
        from .session_ops import start_new_chat
        for open_scene in bpy.data.scenes:
            if (getattr(open_scene, "mixie_session_id", "")
                    or len(getattr(open_scene, "mixie_chat_messages", ()))):
                try:
                    start_new_chat(open_scene)
                except Exception as e:  # noqa: BLE001 — never block a sign-out
                    logger.warning("Fresh chat for %r at sign-out failed: %s", open_scene.name, e)

        # Disconnect WebSocket first (if connected)
        from ...core import get_connection_manager
        manager = get_connection_manager()
        manager.disconnect()

        # Allow auth check to run again on next login
        _auth_check_started = False
        _auto_connect_scheduled = False

        # Session-end telemetry MUST run before the credentials are
        # cleared: capture() drops events without an auth token. The
        # once-guard in capture_session_ended is correct here — a logout
        # ends the session, and a later atexit must not double-fire.
        try:
            from mixar.bootstrap.analytics_module import capture_session_ended
            capture_session_ended("logout")
        except Exception as exc:
            logger.debug("logout session-end capture failed: %s", exc)

        # Delete tokens from keyring, and a guest claim still waiting for a
        # retry: the guest is never claimed into the next seat.
        clear_credentials()
        guest.clear_pending_claim()

        # Clear cached generation configs
        invalidate_generation_caches()
        invalidate_agent_settings()

        # Clear login state
        wm.mixie_chat_is_logged_in = False
        scene.mixie_chat_user_id = ""
        wm.mixie_chat_password = ""
        scene.mixie_chat_credits = 0

        # Clear the billing snapshot + greeting immediately, so the profile
        # card can't show the previous account's plan on the next open.
        _clear_account_name()

        # Clear cached BYOK state so the profile menu and dialog reset
        # when the next user logs in.
        _clear_byok_state_on_logout(wm)
        _clear_referral_state(wm)
        if hasattr(wm, 'mixie_chat_is_guest'):
            wm.mixie_chat_is_guest = False
        guest.mark(False)

        self.report({'INFO'}, "Logged out successfully")

        # A fresh guest takes the signed-out seat (never the old guest's
        # pair); without one the app simply stays signed out.
        _auth_check_started = True
        threading.Thread(
            target=_enter_guest_session, args=(_stay_signed_out,),
            daemon=True, name="MixarGuestSession",
        ).start()
        return {'FINISHED'}


class MIXIE_CHAT_OT_open_dashboard(Operator):
    """Open Mixie web dashboard with seamless auth"""
    bl_idname = "mixie_chat.open_dashboard"
    bl_label = "Open Dashboard"
    bl_description = "Open Mixie web dashboard in your browser"

    def execute(self, context):
        result = open_dashboard_with_handoff()
        if result.get("success"):
            self.report({'INFO'}, result.get("message", n_("Dashboard opened")))
            return {'FINISHED'}

        fallback_url = result.get("url")
        if fallback_url:
            self.report({'WARNING'}, rpt_("{message}. URL: {url}").format(
                message=result.get('message', rpt_('Failed')), url=fallback_url))
        else:
            self.report({'ERROR'}, result.get("message", n_("Failed to open dashboard")))
        return {'CANCELLED'}


class MIXIE_CHAT_OT_refresh_credits(Operator):
    """Refresh credits by fetching latest user info"""
    bl_idname = "mixie_chat.refresh_credits"
    bl_label = "Refresh Credits"
    bl_description = "Refresh your credit balance"

    def execute(self, context):
        logger.info("[RefreshCredits] Operator triggered")

        def _fetch_credits():
            logger.info("[RefreshCredits] Fetching user info...")
            user_info = get_user_info()
            logger.info("[RefreshCredits] Response: %s", user_info)
            if user_info and user_info.get("status") == "success":
                credits = user_info["data"].get("credits", 0)
                logger.info("[RefreshCredits] Got credits: %s", credits)

                def _apply():
                    try:
                        bpy.context.scene.mixie_chat_credits = credits
                        for window in bpy.context.window_manager.windows:
                            for area in window.screen.areas:
                                if area.type == 'AGENT_BUBBLE':
                                    area.tag_redraw()
                        logger.info("[RefreshCredits] Applied credits: %s", credits)
                    except Exception as e:
                        logger.warning("[RefreshCredits] Failed to apply: %s", e)
                    return None

                bpy.app.timers.register(_apply, first_interval=0.0)
            else:
                logger.warning("[RefreshCredits] Failed to fetch: %s", user_info)

        threading.Thread(
            target=_fetch_credits, daemon=True, name="MixarRefreshCredits"
        ).start()
        return {'FINISHED'}


classes = (
    MIXIE_CHAT_OT_login,
    MIXIE_CHAT_OT_logout,
    MIXIE_CHAT_OT_open_dashboard,
    MIXIE_CHAT_OT_refresh_credits,
)


def _delayed_auth_check():
    """Run auth check after a short delay to ensure properties are registered."""
    check_auth_on_startup(None)
    return None  # Don't repeat


def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    # Register startup handler for file loads
    if check_auth_on_startup not in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.append(check_auth_on_startup)

    # Run auth check on initial app startup (with small delay)
    bpy.app.timers.register(_delayed_auth_check, first_interval=0.5)


def unregister():
    global _auth_check_started, _auto_connect_scheduled
    _auth_check_started = False
    _auto_connect_scheduled = False

    # Unregister startup handler
    if check_auth_on_startup in bpy.app.handlers.load_post:
        bpy.app.handlers.load_post.remove(check_auth_on_startup)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
