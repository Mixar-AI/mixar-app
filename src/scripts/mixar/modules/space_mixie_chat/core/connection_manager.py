# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
Connection Manager for Mixie Chat.

Manages the JSON-RPC WebSocket client lifecycle, including:
- Persistent instance ID generation and storage
- WebSocket connection initialization with handshake
- Script execution handler registration
"""

from mixar.config.logging_config import get_logger
from typing import Optional

from mixar.config.config import get_server_url

from ...auth.core.auth import get_access_token
from ..constants import (
    DEFAULT_MAX_RECONNECT_DELAY,
    DEFAULT_PING_INTERVAL,
    DEFAULT_RECONNECT_DELAY,
    DISCONNECT_REASON_AUTH_FAILED,
    JSONRPCMethod,
    SessionState,
)
from .jsonrpc_client import (
    JSONRPCWebSocketClient,
    cleanup_jsonrpc_client,
    create_jsonrpc_client,
    get_jsonrpc_client,
)

logger = get_logger(__name__)


def handle_server_notification(params: dict) -> None:
    """Route one server-originated notification to the right surface.

    Shared by live ``notifications.push`` and the ``notifications.sync``
    catch-up on (re)connect, so reserved types (``update``,
    ``credit_upgrade``) behave identically no matter how the notification
    arrives.
    """
    notif_type = params.get("type", "info")

    if notif_type == "update":
        from mixar.modules.common.updates.core.trigger import trigger_update_check
        trigger_update_check()
        return

    if notif_type == "credit_upgrade":
        # Surface #1 — the sticky "Upgrade" toast (thread-safe store).
        from ...common.notifications.credit_upgrade import push_credit_upgrade
        push_credit_upgrade(params)
        # Surface #2 — a Mixie chat message with the same CTA. This
        # mutates scene data, so marshal it onto the main thread.
        from .main_thread_executor import run_on_main_thread

        def _add_chat_notice(p=params):
            from .credits_notice import add_credit_upgrade_chat_message
            add_credit_upgrade_chat_message(
                title=p.get("title"),
                body=p.get("body", p.get("message")),
                action_url=p.get("action_url"),
            )

        run_on_main_thread(_add_chat_notice)
        return

    from ...common.notifications import get_notification_store
    get_notification_store().push_from_server(params)


class ConnectionManager:
    """
    Singleton managing WebSocket client lifecycle.

    Handles persistent instance ID, WebSocket connection,
    and coordination with QueueProcessor.
    """

    _instance: Optional["ConnectionManager"] = None

    def __new__(cls) -> "ConnectionManager":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def _setup(self) -> None:
        """Initialize internal state (called once)."""
        if self._initialized:
            return

        self._is_initializing = False
        self._is_shutting_down = False
        self._liveness_monitor_running = False
        self._last_transport_live: Optional[bool] = None
        self._initialized = True
        logger.debug("ConnectionManager created")

    def initialize(self) -> bool:
        """
        Initialize the connection manager.

        Prepares for connection. Does not connect yet - call connect() for that.
        Instance ID is now managed by SessionManager via WindowManager property.

        Returns:
            True if initialization succeeded
        """
        self._setup()

        if self._is_initializing:
            logger.warning("ConnectionManager already initializing")
            return False

        self._is_initializing = True

        try:
            # Instance ID is now managed by SessionManager via WindowManager property
            from .session import get_session_manager
            session = get_session_manager()
            # Access instance_id to trigger generation if needed
            instance_id = session.instance_id
            logger.info(f"ConnectionManager initialized with instance_id: {instance_id[:8]}...")
            return True

        except Exception as e:
            logger.error(f"Failed to initialize ConnectionManager: {e}")
            return False
        finally:
            self._is_initializing = False

    def connect(self) -> bool:
        """
        Initiate JSON-RPC WebSocket connection.

        Creates the JSON-RPC client with handshake and registers
        the script execution handler.

        Returns:
            True if connection was initiated successfully
        """
        self._setup()

        from .session import get_session_manager
        session = get_session_manager()

        # Check actual WS client state (source of truth) — scene state can be
        # stale from startup.blend saved while connected.
        client = get_jsonrpc_client()
        if client is not None:
            if self.is_connected:
                logger.debug("Already connected (WS client active)")
                return True
            if client._running.is_set():
                logger.debug("Connection already in progress (WS client running)")
                return True

        # Reset any stale scene state left over from startup.blend or a prior
        # session that didn't clean up.  This ensures the CONNECTING transition
        # below is always valid.
        import bpy
        for s in bpy.data.scenes:
            state = session.get_state(s)
            if state != SessionState.OFFLINE:
                logger.info("Clearing stale scene state: %s was %s", s.name, state.value)
                session.set_state(s, SessionState.OFFLINE)

        # Ensure initialized - instance_id is now managed by SessionManager
        if not session.instance_id:
            if not self.initialize():
                return False

        # Update all scenes to connecting
        session.set_all_scenes_state(SessionState.CONNECTING)

        # Get server URL
        base_url = get_server_url()

        # Define callbacks
        def on_connected():
            if self._is_shutting_down:
                logger.info("JSON-RPC WebSocket connected during shutdown; ignoring")
                return

            from .main_thread_executor import run_on_main_thread
            def _set_idle():
                session.set_all_scenes_state(
                    SessionState.IDLE,
                    only_from={SessionState.OFFLINE, SessionState.CONNECTING},
                )
                # Scenes holding an active turn keep their state (no edge to
                # redraw on), but the status pill/header derive "Reconnecting"
                # from transport liveness — repaint them on the flip back.
                from .ui_utils import redraw_chat_areas
                redraw_chat_areas()
            run_on_main_thread(_set_idle)
            logger.info("JSON-RPC WebSocket connected")

            # Sync pending notifications via JSON-RPC
            client = get_jsonrpc_client()
            if client:
                def _on_sync_result(result):
                    notifications = []
                    if isinstance(result, list):
                        notifications = result
                    elif isinstance(result, dict) and "notifications" in result:
                        notifications = result["notifications"]
                    else:
                        logger.debug(f"notifications.sync result: {result}")
                        return

                    for notif in notifications:
                        handle_server_notification(notif)
                    logger.info(f"notifications.sync returned {len(notifications)} notifications")

                client.send_request("notifications.sync", {}, _on_sync_result)

                def _on_job_sync_result(result):
                    from .main_thread_executor import run_on_main_thread

                    def _apply_sync():
                        from ...common.job_queue.core.queue_manager import (
                            handle_backend_job_sync,
                        )
                        count = handle_backend_job_sync(result)
                        if count:
                            logger.info("job.sync reconciled %d local queue jobs", count)

                    run_on_main_thread(_apply_sync)

                client.send_request(JSONRPCMethod.JOB_SYNC, {}, _on_job_sync_result)

                # #1258: a turn that outlived the disconnect is invisible to
                # the user — ask the server which local sessions have a turn
                # still running, or abandoned unwatched by the drain, and
                # surface "Resume previous task" for those. A turn that ended
                # in front of the user is never announced.
                try:
                    from .turn_resume import check_orphaned_turns

                    check_orphaned_turns()
                except Exception:
                    logger.exception("orphaned-turn check failed (non-fatal)")

            # Report client version in the background (REST)
            import threading

            def _report_version():
                from ...auth.core.device import get_device_id
                from ...common.notifications import report_client_version
                from ...common.updates.core.update_checker import get_runtime_version
                # Same version source as the agent chat X-Client-Version
                # header, so the PUT and the header can never disagree.
                version = get_runtime_version()
                token = get_access_token()
                if token and version:
                    report_client_version(
                        base_url, token, version, device_id=get_device_id()
                    )

            threading.Thread(target=_report_version, daemon=True).start()

            # P1-6: if this (re)connect re-activated a session whose last
            # build died with a dead Blender session (a PARKED turn), the
            # backend decides whether the tail is small enough to
            # auto-continue. Fail-quiet — never break the connect path.
            try:
                from .parked_resume import schedule_after_connect
                schedule_after_connect(base_url)
            except Exception as e:
                logger.debug(f"[PARKED] auto-resume skipped: {e}")

        def on_disconnected(reason: str):
            if self._is_shutting_down:
                logger.info(f"JSON-RPC WebSocket disconnected: {reason}")
                return
            from .main_thread_executor import run_on_main_thread
            # An auth failure stops the reconnect loop — that disconnect is
            # terminal. Anything else is a transient drop the client will
            # auto-reconnect from, so a running agent turn (BUSY / MODIFYING /
            # AWAITING_INPUT) must survive it: the turn streams over its own
            # SSE connection and the backend keeps executing — wiping its
            # state here made the client refuse every post-reconnect script
            # with "Agent session not active" while showing an idle pill.
            terminal = reason == DISCONNECT_REASON_AUTH_FAILED
            def _set_offline():
                session.on_transport_disconnect(terminal=terminal)
                # Preserved active states produce no state edge, so repaint
                # explicitly — the pill/header show "Reconnecting" from
                # transport liveness, not from scene state.
                from .ui_utils import redraw_chat_areas
                redraw_chat_areas()
            run_on_main_thread(_set_offline)
            logger.info(f"JSON-RPC WebSocket disconnected: {reason}")

        def on_script_execute(
            script: str,
            request_id: Optional[str] = None,
            tool_name: str = "unknown",
            session_id: str = "",
            agent_ctx: Optional[dict] = None,
        ) -> Optional[dict]:
            """Queue script for main thread execution (non-blocking)."""
            if not session.has_active_session():
                logger.warning(
                    "Rejecting script %s (id: %s) — no active agent session",
                    tool_name, request_id,
                )
                return {"success": False, "error": "Agent session not active"}

            from .main_thread_executor import queue_script_request
            if request_id:
                queue_script_request(
                    script, request_id, tool_name, session_id, agent_ctx
                )
                return None
            else:
                queue_script_request(
                    script, "notification", tool_name, session_id, agent_ctx
                )
                return None

        def on_tool_start(params: dict):
            """Handle tool start notification."""
            pass  # Logging handled in main_thread_executor

        def on_tool_end(params: dict):
            """Handle tool end notification."""
            pass  # Logging handled in main_thread_executor

        def on_notifications_push(params: dict):
            """Handle notifications.push — route to the shared handler."""
            handle_server_notification(params)

        def on_job_update(params: dict):
            """Handle job.update — reconcile the matching local queue job."""
            from .main_thread_executor import run_on_main_thread

            def _apply_update():
                from ...common.job_queue.core.queue_manager import (
                    handle_backend_job_update,
                )
                handle_backend_job_update(params)

            run_on_main_thread(_apply_update)

        def on_sandbox_control(params: dict) -> dict:
            """Backend asked this (parent) instance to manage its sandbox child."""
            from mixar.bootstrap.sandbox_supervisor import handle_sandbox_control
            return handle_sandbox_control(params)

        def on_llm_request(params: dict, request_id) -> None:
            """Relay one backend llm.request to the user's local model server.

            Runs on the WS receive thread — which must never block — so the
            blocking localhost HTTP call happens on its own daemon thread and
            the reply goes back through client.queue_response (thread-safe
            Queue). Returning None tells the JSON-RPC client the response is
            deferred. The worker never touches Blender state.
            """
            import threading

            def _respond(result: dict) -> None:
                if not request_id:
                    return  # notification — nothing to answer
                from .jsonrpc_client import get_jsonrpc_client
                ws_client = get_jsonrpc_client()
                if ws_client and ws_client.is_connected:
                    ws_client.queue_response(request_id, result)
                else:
                    logger.warning(
                        "llm.request %s finished after disconnect — reply dropped",
                        request_id,
                    )

            def _relay():
                responded = {"done": False}

                def _respond_once(result: dict) -> None:
                    if responded["done"]:
                        return
                    responded["done"] = True
                    _respond(result)

                try:
                    from ...local_models.core.relay import handle_llm_request
                    handle_llm_request(params, _respond_once)
                except Exception as exc:  # noqa: BLE001 - must always answer
                    logger.error("llm.request relay failed: %s", exc, exc_info=True)
                    _respond_once({
                        "error": {"code": "relay_internal", "message": str(exc)},
                    })

            threading.Thread(
                target=_relay, daemon=True, name="MixarLocalLLMRelay"
            ).start()
            return None  # deferred — _respond() replies from the worker

        def on_addon_project_request(method: str, params: dict, request_id) -> None:
            """Run bounded project I/O off-thread and Blender reload on main."""
            import threading

            if not request_id:
                return None
            if not session.has_active_session():
                return {"success": False, "error": {
                    "code": "session_inactive",
                    "message": "Agent session not active",
                }}
            request_client = client

            def _respond(result: dict) -> None:
                ws_client = get_jsonrpc_client()
                if ws_client is request_client and request_client.is_connected:
                    request_client.queue_response(request_id, result)
                else:
                    logger.warning("project request %s finished after disconnect", request_id)

            def _worker() -> None:
                from mixar.modules.addon_project.constants import (
                    RPC_RUN_CHECKS,
                    RPC_SET_ENABLED,
                )
                from mixar.modules.addon_project.service import get_addon_project_service

                service = get_addon_project_service()
                # Blender registration APIs must run on the main thread:
                # reload-checks AND set_enabled both reach addon_utils
                # enable/disable (register()/unregister(), prefs writes).
                # Static checks and every other project operation stay on
                # this worker.
                needs_main_thread = method == RPC_SET_ENABLED or (
                    method == RPC_RUN_CHECKS and bool(params.get("reload_blender"))
                )
                if needs_main_thread:
                    if method == RPC_RUN_CHECKS:
                        static_params = dict(params)
                        static_params["reload_blender"] = False
                        static_result = service.dispatch(method, static_params)
                        if not static_result.get("success"):
                            _respond(static_result)
                            return

                    from .main_thread_executor import run_on_main_thread

                    def _run_and_respond() -> None:
                        _respond(service.dispatch(method, params))

                    run_on_main_thread(_run_and_respond)
                    return
                _respond(service.dispatch(method, params))

            threading.Thread(
                target=_worker,
                daemon=True,
                name="MixarAddonProjectRPC",
            ).start()
            return None

        # Create JSON-RPC WebSocket client
        self._is_shutting_down = False
        # Re-arm the script executor: a prior disconnect(update_session_state=
        # False) (bootstrap unregister / Reload Scripts) latches its shutdown
        # flag, which would silently drop every script request on the new
        # connection — the backend then times out on every tool call.
        from .main_thread_executor import resume as resume_executor
        resume_executor()
        client = create_jsonrpc_client(
            host=base_url,
            connection_id=session.instance_id,
            token_getter=get_access_token,
            reconnect_delay=DEFAULT_RECONNECT_DELAY,
            max_reconnect_delay=DEFAULT_MAX_RECONNECT_DELAY,
            ping_interval=DEFAULT_PING_INTERVAL,
            on_script_execute=on_script_execute,
            on_tool_start=on_tool_start,
            on_tool_end=on_tool_end,
            on_connected=on_connected,
            on_disconnected=on_disconnected,
            on_notification=on_notifications_push,
            on_job_update=on_job_update,
            on_sandbox_control=on_sandbox_control,
            on_llm_request=on_llm_request,
            on_addon_project_request=on_addon_project_request,
        )

        # Connect
        if client.connect():
            logger.info("JSON-RPC WebSocket connection initiated")
            self._start_liveness_monitor()
            return True
        else:
            session.set_all_scenes_state(SessionState.OFFLINE)
            logger.error("Failed to connect JSON-RPC WebSocket client")
            return False

    def disconnect(self, update_session_state: bool = True) -> None:
        """
        Gracefully disconnect the WebSocket connection and clean up resources.
        """
        self._setup()

        from .session import get_session_manager
        session = get_session_manager()

        if not update_session_state:
            self._is_shutting_down = True

        # Disconnect JSON-RPC WebSocket client
        cleanup_jsonrpc_client()

        # Clean up main thread executor
        from .main_thread_executor import cleanup
        cleanup(shutdown=not update_session_state)

        # Update session state unless Blender is already in restricted
        # shutdown, where bpy.data.scenes is no longer available.
        if update_session_state:
            session.set_all_scenes_state(SessionState.OFFLINE)
            self._is_shutting_down = False

        logger.info("WebSocket connections disconnected")

    def reconnect(self) -> bool:
        """
        Reconnect the WebSocket.

        Disconnects if connected, then connects again.

        Returns:
            True if reconnection was initiated successfully
        """
        self.disconnect()
        return self.connect()

    @property
    def instance_id(self) -> Optional[str]:
        """Get the current instance ID from SessionManager."""
        self._setup()
        from .session import get_session_manager
        return get_session_manager().instance_id

    @property
    def is_connected(self) -> bool:
        """Check if JSON-RPC WebSocket is currently connected."""
        self._setup()
        client = get_jsonrpc_client()
        return client is not None and client.is_connected

    @property
    def is_transport_live(self) -> bool:
        """Fast liveness signal for status displays only.

        False as soon as the socket has gone recv-silent past
        WS_UI_STALE_THRESHOLD — well before is_connected flips on the
        teardown watchdog. Send-gating must keep using is_connected.
        """
        self._setup()
        client = get_jsonrpc_client()
        return client is not None and client.is_transport_live

    def _start_liveness_monitor(self) -> None:
        """Repaint status surfaces when transport liveness flips.

        The pill/header compute their label from is_transport_live at draw
        time, but nothing tags a redraw when a connection dies silently —
        there is no scene-state edge until the teardown watchdog fires, so
        the stale "Idle/Connected" pill would sit unrepainted for the whole
        zombie window. A cheap main-thread poll closes that gap; it stops
        itself once the client is gone.
        """
        if self._liveness_monitor_running:
            return

        import bpy

        self._liveness_monitor_running = True
        self._last_transport_live = None

        def _poll():
            if self._is_shutting_down or get_jsonrpc_client() is None:
                self._liveness_monitor_running = False
                self._last_transport_live = None
                return None
            try:
                live = self.is_transport_live
                if live != self._last_transport_live:
                    self._last_transport_live = live
                    from .ui_utils import redraw_chat_areas
                    redraw_chat_areas()
            except Exception:
                logger.debug("liveness monitor poll failed", exc_info=True)
            return 2.0

        # persistent=True: the WS connection survives file loads, so the
        # monitor must too (non-persistent timers are dropped on load).
        bpy.app.timers.register(_poll, first_interval=2.0, persistent=True)

    @property
    def connection_state(self) -> SessionState:
        """Get current connection state from the active scene."""
        import bpy
        from .session import get_session_manager
        scene = bpy.context.scene
        return get_session_manager().get_state(scene) if scene else SessionState.OFFLINE

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton instance. Useful for testing."""
        if cls._instance is not None:
            cls._instance._initialized = False
            cls._instance._is_initializing = False


# Module-level singleton accessor
_connection_manager: Optional[ConnectionManager] = None


def get_connection_manager() -> ConnectionManager:
    """Get the global ConnectionManager singleton."""
    global _connection_manager
    if _connection_manager is None:
        _connection_manager = ConnectionManager()
    return _connection_manager
