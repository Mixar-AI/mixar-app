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
            run_on_main_thread(_set_idle)
            logger.info("JSON-RPC WebSocket connected")

            # Sync pending notifications via JSON-RPC
            client = get_jsonrpc_client()
            if client:
                from ...common.notifications import get_notification_store
                store = get_notification_store()

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
                        if notif.get("type") == "update":
                            from mixar.modules.common.updates.core.trigger import trigger_update_check
                            trigger_update_check()
                        else:
                            store.push_from_server(notif)
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

            # Report client version in the background (REST)
            import threading

            def _report_version():
                from ...common.notifications import report_client_version
                from ...common.updates.core.update_checker import get_current_version
                version = get_current_version()
                token = get_access_token()
                if token:
                    report_client_version(base_url, token, version)

            threading.Thread(target=_report_version, daemon=True).start()

        def on_disconnected(reason: str):
            if self._is_shutting_down:
                logger.info(f"JSON-RPC WebSocket disconnected: {reason}")
                return
            from .main_thread_executor import run_on_main_thread
            def _set_offline():
                session.set_all_scenes_state(SessionState.OFFLINE)
            run_on_main_thread(_set_offline)
            logger.info(f"JSON-RPC WebSocket disconnected: {reason}")

        def on_script_execute(script: str, request_id: Optional[str] = None, tool_name: str = "unknown", session_id: str = "") -> Optional[dict]:
            """Queue script for main thread execution (non-blocking)."""
            if not session.has_active_session():
                logger.warning(
                    "Rejecting script %s (id: %s) — no active agent session",
                    tool_name, request_id,
                )
                return {"success": False, "error": "Agent session not active"}

            from .main_thread_executor import queue_script_request
            if request_id:
                queue_script_request(script, request_id, tool_name, session_id)
                return None
            else:
                queue_script_request(script, "notification", tool_name, session_id)
                return None

        def on_tool_start(params: dict):
            """Handle tool start notification."""
            pass  # Logging handled in main_thread_executor

        def on_tool_end(params: dict):
            """Handle tool end notification."""
            pass  # Logging handled in main_thread_executor

        def on_notifications_push(params: dict):
            """Handle notifications.push — push to toast overlay."""
            notif_type = params.get("type", "info")
            if notif_type == "update":
                from mixar.modules.common.updates.core.trigger import trigger_update_check
                trigger_update_check()
                return

            from ...common.notifications import get_notification_store
            store = get_notification_store()
            store.push(
                type_str=notif_type,
                title=params.get("title", ""),
                body=params.get("body", params.get("message", "")),
                priority=params.get("priority", "normal"),
                action_url=params.get("action_url"),
                id=params.get("id"),
            )

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
        )

        # Connect
        if client.connect():
            logger.info("JSON-RPC WebSocket connection initiated")
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
