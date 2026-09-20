# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
JSON-RPC 2.0 WebSocket client for Blender agent communication.

Handles bidirectional RPC:
- Connection with handshake (system.handshake)
- Keep-alive pings (system.ping)
- Script execution requests from server (blender.execute_script)
- Tool lifecycle notifications (agent.tool_start, agent.tool_end)
"""

from mixar.config.logging_config import get_logger
from typing import Optional

from ..constants import JSONRPCMethod

try:
    import websocket
except ImportError:
    websocket = None

logger = get_logger(__name__)


class SocketDispatch:
    def _handle_message(self, msg: dict) -> None:
        """Handle incoming JSON-RPC message."""
        # Check if it's a response (to our ping, handshake, or send_request)
        if "result" in msg or "error" in msg:
            msg_id = msg.get("id")
            if msg_id:
                with self._pending_lock:
                    cb = self._pending_callbacks.pop(msg_id, None)
                    self._pending_deadlines.pop(msg_id, None)
                if cb is not None:
                    try:
                        payload = msg.get("result") if "result" in msg else msg.get("error")
                        cb(payload)
                    except Exception as e:
                        logger.error(f"Error in response callback for {msg_id}: {e}")
            return

        # It's a request or notification
        method = msg.get("method")
        params = msg.get("params", {})
        request_id = msg.get("id")  # None for notifications

        if method == 'agent.history_read':
            if self._archive_sync:
                self._archive_sync.read(params, request_id)
            elif request_id:
                self.queue_response(request_id, {'status': 'unavailable'})

        elif method == JSONRPCMethod.BLENDER_EXECUTE_SCRIPT:
            self._handle_execute_script(params, request_id)

        elif method == JSONRPCMethod.BLENDER_LIVENESS:
            self._handle_liveness(request_id)

        elif method == JSONRPCMethod.AGENT_SANDBOX_CONTROL:
            self._handle_sandbox_control(params, request_id)

        elif method == JSONRPCMethod.LLM_REQUEST:
            self._handle_llm_request(params, request_id)

        elif isinstance(method, str) and method.startswith(JSONRPCMethod.ADDON_PROJECT_PREFIX):
            self._handle_addon_project_request(method, params, request_id)

        elif isinstance(method, str) and method.startswith(JSONRPCMethod.AGENT_EXECUTION_PREFIX):
            self._handle_execution_request(method, params, request_id)

        elif method == JSONRPCMethod.AGENT_TOOL_START:
            if self._on_tool_start:
                try:
                    self._on_tool_start(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_start callback: {e}")

        elif method == JSONRPCMethod.AGENT_TOOL_EXECUTING:
            if self._on_tool_executing:
                try:
                    self._on_tool_executing(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_executing callback: {e}")

        elif method == JSONRPCMethod.AGENT_TOOL_END:
            if self._on_tool_end:
                try:
                    self._on_tool_end(params)
                except Exception as e:
                    logger.error(f"Error in on_tool_end callback: {e}")

        elif method == JSONRPCMethod.NOTIFICATIONS_PUSH:
            if self._on_notification:
                try:
                    self._on_notification(params)
                except Exception as e:
                    logger.error(f"Error in on_notification callback: {e}")

        elif method == JSONRPCMethod.JOB_UPDATE:
            if self._on_job_update:
                try:
                    self._on_job_update(params)
                except Exception as e:
                    logger.error(f"Error in on_job_update callback: {e}")

        elif method in (
            JSONRPCMethod.AGENT_TURN_STARTED,
            JSONRPCMethod.AGENT_TURN_EVENT,
            JSONRPCMethod.AGENT_TURN_ENDED,
            "agent.command.result", "agent.command.delivered",
        ):
            # Backend-started turns of an open run (wake-ups). Notifications
            # only; the handler marshals bpy work to the main thread itself.
            if self._on_turn_event:
                try:
                    self._on_turn_event(method, params)
                except Exception as e:
                    logger.error(f"Error in on_turn_event callback ({method}): {e}")

        else:
            logger.warning(f"Unknown JSON-RPC method: {method}")

    def _handle_execution_request(
        self, method: str, params: dict, request_id: Optional[str]
    ) -> None:
        """Handle a harness v3 ``agent.execution.*`` request (parent side).

        The callback schedules its bpy work on the main thread and replies
        through ``queue_response`` (returns None). A synchronous dict is an
        immediate refusal. A client without the handler (a headless worker)
        answers ``capability_unavailable``.
        """
        result = None
        if self._on_execution_request:
            try:
                result = self._on_execution_request(method, params, request_id)
                if result is None:
                    return
            except Exception as exc:
                logger.error("execution request %s failed: %s", method, exc)
                result = {"success": False, "error": str(exc), "error_type": "handler_error"}
        else:
            result = {
                "success": False,
                "error": "execution protocol unavailable on this client",
                "error_type": "capability_unavailable",
            }
        if request_id:
            self.queue_response(request_id, result)

    def _handle_addon_project_request(
        self, method: str, params: dict, request_id: Optional[str]
    ) -> None:
        """Handle a capability-scoped local project operation.

        The callback normally defers disk work to a worker and replies through
        ``queue_response``. A synchronous result remains useful in tests and
        for immediate refusals.
        """
        result = None
        if self._on_addon_project_request:
            try:
                result = self._on_addon_project_request(method, params, request_id)
                if result is None:
                    return
            except Exception as exc:
                logger.error("add-on project request failed: %s", exc)
                result = {
                    "success": False,
                    "error": {
                        "code": "handler_error",
                        "message": "The local add-on project handler failed",
                    },
                }
        else:
            result = {
                "success": False,
                "error": {
                    "code": "capability_unavailable",
                    "message": "Add-on Project Mode is unavailable in this client",
                },
            }
        if request_id and result is not None:
            self.queue_response(request_id, result)

    def _handle_execute_script(self, params: dict, request_id: Optional[str]) -> None:
        """Handle script execution request.

        The callback may return None to indicate async handling - in that case,
        the response will be sent later via the execution response queue.
        """
        script = params.get("script", "")
        tool_name = params.get("tool_name", "unknown")
        session_id = params.get("session_id", "")
        agent_ctx = params.get("agent_ctx")
        # Optional v3 task envelope (harness v3 PR 1). Passed as a keyword
        # ONLY when present so older five-positional callbacks keep working.
        envelope = params.get("envelope")

        if self._on_script_execute:
            try:
                if isinstance(envelope, dict):
                    result = self._on_script_execute(
                        script, request_id, tool_name, session_id, agent_ctx,
                        envelope=envelope,
                    )
                else:
                    result = self._on_script_execute(
                        script, request_id, tool_name, session_id, agent_ctx
                    )
                if result is None:
                    # Async handling - response will be sent via response queue
                    return
            except Exception as e:
                logger.error(f"Script execution error: {e}")
                result = {
                    "success": False,
                    "error": str(e),
                }
        else:
            result = {
                "success": False,
                "error": "No script execution handler registered",
            }

        # Send response if it's a request (has id) and we have a result
        if request_id and result is not None:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": result,
            }
            self._enqueue_frame(response, required=True)

    def _handle_llm_request(self, params: dict, request_id: Optional[str]) -> None:
        """Handle a server-initiated llm.request (local model relay).

        Mirrors ``_handle_execute_script``'s deferred contract: the callback
        returns ``None`` to indicate async handling — it spawns its own worker
        thread and replies later via ``queue_response(request_id, result)``.
        The WS receive thread must NEVER run the (up to ~minutes-long) local
        HTTP call itself; a synchronous return here is only used for
        immediate refusals.

        Failure results reuse the shape the relay layer defines —
        ``{"error": {"code", "message"}}`` — sent through the same
        ``queue_response`` path as every other response (matching how
        execute_script failures travel as result payloads).
        """
        result: Optional[dict] = None
        if self._on_llm_request:
            try:
                result = self._on_llm_request(params, request_id)
                if result is None:
                    # Deferred — the handler responds via queue_response later.
                    return
            except Exception as e:
                logger.error(f"llm.request handler error: {e}")
                result = {
                    "error": {"code": "relay_internal", "message": str(e)},
                }
        else:
            result = {
                "error": {
                    "code": "relay_unavailable",
                    "message": "No local LLM relay handler registered",
                },
            }
        if request_id and result is not None:
            self.queue_response(request_id, result)

    def _handle_sandbox_control(self, params: dict, request_id: Optional[str]) -> None:
        """Handle a server-initiated agent.sandbox_control request (parent side).

        Delegates to the on_sandbox_control callback (the sandbox supervisor) and
        replies with its result so the backend can confirm spawn/shutdown.
        """
        result = {"success": False, "error": "no sandbox control handler"}
        if self._on_sandbox_control:
            try:
                result = self._on_sandbox_control(params) or {"success": True}
            except Exception as e:
                logger.error(f"sandbox_control handler error: {e}")
                result = {"success": False, "error": str(e)}
        if request_id:
            self.queue_response(request_id, result)
