# SPDX-FileCopyrightText: 2025 Mixar Authors
# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Authentication operators for Mixie Chat.

Provides operators for user login and logout functionality.
"""

import threading

import bpy
from bpy.app.handlers import persistent
from bpy.types import Operator

from mixar.config.logging_config import get_logger

from ....auth.core.auth import (
    clear_credentials,
    get_access_token,
    get_user_info,
    open_dashboard_with_handoff,
    refresh_access_token,
)
from ....auth.core.auth_hooks import (
    invalidate_generation_caches,
    maybe_show_onboarding,
    refresh_generation_caches,
)
from ....auth.core.sso import sso_login
from ...core import account_usage

logger = get_logger(__name__)


_auto_connect_scheduled = False


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


def _schedule_byok_fetch():
    """Trigger BYOK state + models-catalog refresh after login.

    Runs via a small-delay timer so the byok operators have time to be
    registered (UI modules load in time-budgeted batches post-bootstrap).
    Silent no-op if the operators aren't available yet — BYOK falls back
    to "inactive" + an empty models-catalog cache, both safe defaults.
    """
    def _try():
        try:
            if hasattr(bpy.types, 'MIXAR_BYOK_OT_fetch_state'):
                bpy.ops.mixar_byok.fetch_state()
            if hasattr(bpy.types, 'MIXAR_BYOK_OT_fetch_models_catalog'):
                bpy.ops.mixar_byok.fetch_models_catalog()
        except Exception as e:
            logger.debug("BYOK fetch trigger failed: %s", e)
        return None  # Don't repeat

    bpy.app.timers.register(_try, first_interval=0.5)


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
        ('byok_form_api_key', ''),
        ('byok_form_openrouter_model', ''),
        ('byok_form_codex_bundle', ''),
        ('byok_dialog_state', 'IDLE'),
        ('byok_last_error', ''),
    ):
        if hasattr(wm, attr):
            try:
                setattr(wm, attr, default)
            except Exception as e:
                logger.debug("Failed clearing %s on logout: %s", attr, e)

    try:
        from mixar.modules.byok.core import model_suggestions
        model_suggestions.clear()
    except Exception as e:
        logger.debug("Failed clearing models-catalog cache on logout: %s", e)


def _schedule_apply_login(user_info: dict, refreshed: bool) -> None:
    """Schedule main-thread bpy property updates after successful auth.

    Called from a daemon thread — uses bpy.app.timers (thread-safe) to
    write bpy properties back on the main thread.
    """
    def _apply() -> None:
        global _auth_check_started
        try:
            wm = bpy.context.window_manager
            scene = bpy.context.scene
            wm.mixie_chat_is_logged_in = True
            if hasattr(wm, 'mixie_chat_session_expired'):
                wm.mixie_chat_session_expired = False
            wm.mixie_chat_login_error = ""
            email = user_info["data"].get("email", "")
            scene.mixie_chat_user_id = email
            scene.mixie_chat_credits = user_info["data"].get("credits", 0)
            account_usage.apply_user_info(wm, user_info["data"])
            if refreshed:
                logger.info("Token refreshed successfully on startup")
            refresh_generation_caches()
            maybe_show_onboarding(email)
            _auto_connect_websocket()
            _schedule_byok_fetch()
        except Exception as e:
            logger.warning("Auth state apply failed: %s", e)
        finally:
            _auth_check_started = False
        return None  # Don't repeat

    bpy.app.timers.register(_apply, first_interval=0.0)


def _auth_check_background() -> None:
    """Validate/refresh the stored token on a daemon thread.

    All HTTP I/O (get_user_info, refresh_access_token) happens here.
    bpy property writes are handed back to the main thread via a timer.
    """
    global _auth_check_started
    user_info = get_user_info()
    if user_info and user_info.get("status") == "success":
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

    # A definitive 401/403 (or a missing token) requires reauthentication.
    logger.info("Token refresh was definitively rejected, clearing credentials")
    clear_credentials()

    def _mark_expired():
        wm = getattr(bpy.context, 'window_manager', None)
        if wm:
            if hasattr(wm, 'mixie_chat_session_expired'):
                wm.mixie_chat_session_expired = True
            if hasattr(wm, 'mixie_chat_login_error'):
                wm.mixie_chat_login_error = ""
        return None

    bpy.app.timers.register(_mark_expired, first_interval=0.0)

    # Run SSO on this same background thread (it blocks waiting for browser)
    try:
        result = sso_login()
    except Exception as e:
        logger.error("Auto SSO login failed: %s", e)
        result = {"success": False, "message": str(e)}

    # Fetch user info on this background thread (not on main thread)
    user_info = None
    if result.get("success"):
        user_info = get_user_info()

    def _apply_sso_result():
        global _auth_check_started
        wm = getattr(bpy.context, 'window_manager', None)
        if not wm:
            _auth_check_started = False
            return None
        try:
            if hasattr(wm, 'mixie_chat_is_logging_in'):
                wm.mixie_chat_is_logging_in = False

            if result.get("success"):
                wm.mixie_chat_is_logged_in = True
                if hasattr(wm, 'mixie_chat_session_expired'):
                    wm.mixie_chat_session_expired = False
                wm.mixie_chat_login_error = ""

                if user_info and user_info.get("status") == "success":
                    email = user_info["data"].get("email", "")
                    scene = bpy.context.scene
                    if scene is not None:
                        scene.mixie_chat_user_id = email
                        scene.mixie_chat_credits = user_info["data"].get("credits", 0)
                    account_usage.apply_user_info(wm, user_info["data"])

                    refresh_generation_caches()
                    maybe_show_onboarding(email)
                    _auto_connect_websocket()
                    _schedule_byok_fetch()
                    logger.info("Auto SSO re-login completed successfully")
            else:
                if hasattr(wm, 'mixie_chat_login_error'):
                    wm.mixie_chat_login_error = (
                        "Session expired. Please log in again."
                    )
                logger.warning("Auto SSO re-login failed: %s", result.get('message'))
        except Exception as e:
            logger.warning("SSO result apply failed: %s", e)
        finally:
            _auth_check_started = False
        return None

    bpy.app.timers.register(_apply_sso_result, first_interval=0.0)


_auth_check_started = False


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


class MIXIE_CHAT_OT_login(Operator):
    """Login to Mixie Chat via browser SSO"""
    bl_idname = "mixie_chat.login"
    bl_label = "Login"
    bl_description = "Login to Mixie Chat via browser SSO"

    def execute(self, context):
        wm = context.window_manager

        # Set loading state and force redraw
        wm.mixie_chat_is_logging_in = True
        wm.mixie_chat_login_error = ""

        for area in context.screen.areas:
            if area.type == 'MIXIE_CHAT':
                area.tag_redraw()

        # Run SSO on a background thread (blocks waiting for browser callback)
        def _sso_thread():
            try:
                result = sso_login()
                logger.info("SSO login returned: success=%s", result.get("success"))
            except Exception as e:
                logger.error("SSO login failed with exception: %s", e)
                result = {"success": False, "message": str(e)}

            # Fetch user info on this background thread (not on main thread)
            user_info = None
            if result.get("success"):
                user_info = get_user_info()

            def _apply_result():
                try:
                    live_wm = bpy.context.window_manager
                    live_wm.mixie_chat_is_logging_in = False

                    if result["success"]:
                        live_wm.mixie_chat_login_error = ""
                        live_wm.mixie_chat_is_logged_in = True
                        if hasattr(live_wm, 'mixie_chat_session_expired'):
                            live_wm.mixie_chat_session_expired = False

                        if user_info and user_info.get("status") == "success":
                            email = user_info["data"].get("email", "")
                            scene = bpy.context.scene
                            if scene is not None:
                                scene.mixie_chat_user_id = email
                                scene.mixie_chat_credits = user_info["data"].get("credits", 0)
                            account_usage.apply_user_info(live_wm, user_info["data"])

                            refresh_generation_caches()
                            maybe_show_onboarding(email)
                            _auto_connect_websocket()
                            _schedule_byok_fetch()
                            logger.info("SSO login completed — user is logged in")
                    else:
                        msg = result.get("message", "Login failed")
                        live_wm.mixie_chat_login_error = msg
                        logger.warning("SSO login failed: %s", msg)

                    # Redraw Mixie Chat areas to reflect new auth state
                    for window in bpy.context.window_manager.windows:
                        for area in window.screen.areas:
                            if area.type == 'MIXIE_CHAT':
                                area.tag_redraw()
                except Exception as e:
                    logger.error("SSO result apply failed: %s", e)
                return None  # Don't repeat

            bpy.app.timers.register(_apply_result, first_interval=0.0)

        threading.Thread(
            target=_sso_thread, daemon=True, name="MixarSSOLogin"
        ).start()
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

        # Disconnect WebSocket first (if connected)
        from ...core import get_connection_manager
        manager = get_connection_manager()
        manager.disconnect()

        # Allow auth check to run again on next login
        _auth_check_started = False
        _auto_connect_scheduled = False

        # Delete tokens from keyring
        clear_credentials()

        # Clear cached generation configs
        invalidate_generation_caches()

        # Clear login state
        wm.mixie_chat_is_logged_in = False
        scene.mixie_chat_user_id = ""
        wm.mixie_chat_password = ""
        scene.mixie_chat_credits = 0
        account_usage.clear(wm)

        # Clear cached BYOK state so the profile menu and dialog reset
        # when the next user logs in.
        _clear_byok_state_on_logout(wm)

        self.report({'INFO'}, "Logged out successfully")
        return {'FINISHED'}


class MIXIE_CHAT_OT_open_dashboard(Operator):
    """Open Mixie web dashboard with seamless auth"""
    bl_idname = "mixie_chat.open_dashboard"
    bl_label = "Open Dashboard"
    bl_description = "Open Mixie web dashboard in your browser"

    def execute(self, context):
        result = open_dashboard_with_handoff()
        if result.get("success"):
            self.report({'INFO'}, result.get("message", "Dashboard opened"))
            return {'FINISHED'}

        fallback_url = result.get("url")
        if fallback_url:
            self.report({'WARNING'}, f"{result.get('message', 'Failed')}. URL: {fallback_url}")
        else:
            self.report({'ERROR'}, result.get("message", "Failed to open dashboard"))
        return {'CANCELLED'}


class MIXIE_CHAT_OT_refresh_credits(Operator):
    """Refresh the account summary from the authenticated user endpoint."""
    bl_idname = "mixie_chat.refresh_credits"
    bl_label = "Refresh Credits"
    bl_description = "Refresh your credit balance"

    def execute(self, context):
        account_usage.request_refresh(context.window_manager, force=True)
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
