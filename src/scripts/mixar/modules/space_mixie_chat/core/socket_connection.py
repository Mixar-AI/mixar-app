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

import json
from mixar.config.logging_config import get_logger
import time
from queue import Empty
from typing import Optional

from ..constants import DISCONNECT_REASON_AUTH_FAILED, JSONRPCMethod
from .jsonrpc_frames import HANDSHAKE_AUTH_FAILED, HANDSHAKE_OK, HANDSHAKE_TRANSIENT, wait_for_handshake

try:
    import websocket
except ImportError:
    websocket = None

logger = get_logger(__name__)


class SocketConnection:
    def _run_loop(self) -> None:
        """Main loop running in background thread."""
        while self._running.is_set():
            try:
                if self._do_connect():
                    self._receive_loop()
            except Exception as e:
                logger.error(f"JSON-RPC run loop error: {e}")

            if self._reauth_stop:
                self._reauth_stop.set()
                self._reauth_stop = None
            if self._writer:
                self._writer[0].set()
                self._writer[1].join(timeout=11)
                self._writer = None
            # Handle disconnection
            self._connected = False
            self._handshake_complete = False

            # Clear pending callbacks to prevent stale responses from leaking
            with self._pending_lock:
                callbacks = list(self._pending_callbacks.values())
                self._pending_callbacks.clear()
                self._pending_deadlines.clear()
            for callback in callbacks:
                try:
                    callback({"code": -32020, "message": "Connection lost; delivery is uncertain", "data": {"uncertain": True}})
                except Exception:
                    logger.debug("Disconnected request callback failed", exc_info=True)

            # Drain stale outbound messages to prevent them leaking into a new session
            drained = 0
            while not self._outbound.empty():
                try:
                    self._outbound.get_nowait()
                    drained += 1
                except Empty:
                    break
            if drained:
                logger.info(f"Cleared {drained} stale outbound messages on disconnect")

            if self._on_disconnected:
                try:
                    self._on_disconnected("Connection lost")
                except Exception as e:
                    logger.error(f"Error in on_disconnected callback: {e}")

            if self._running.is_set():
                logger.info(f"Reconnecting in {self._current_delay:.1f}s...")
                time.sleep(self._current_delay)
                self._current_delay = min(
                    self._current_delay * 2, self._max_reconnect_delay
                )

    def _do_connect(self) -> bool:
        """Establish connection and perform handshake.

        Returns False on ANY failure; the run loop retries after its backoff
        unless this method cleared ``_running``. Only a confirmed auth
        rejection whose token refresh is not retryable stops the loop — a
        backend that is down or still warming up produces connection
        errors, handshake timeouts and non-4001 closes, none of which are
        auth failures and all of which must keep the loop alive so the
        client reconnects by itself once the backend is back.
        """
        token = None
        try:
            logger.info(f"Connecting to {self.ws_url}")

            # Get auth token - after a confirmed auth rejection, refresh it
            # first (an access token that expired during an outage is the
            # common case) and stop only when the refresh path says a
            # retry can never help.
            token = self._token_getter() if self._token_getter else None
            if self._auth.failure_count > 0:
                refreshed, refresh_retryable = self._try_refresh_token()
                if refreshed:
                    token = refreshed
                if self._auth.should_stop(refresh_retryable):
                    if self._on_disconnected:
                        self._on_disconnected(DISCONNECT_REASON_AUTH_FAILED)
                    self._running.clear()
                    return False
            headers = [f"Authorization: Bearer {token}"] if token else []
            # Extend the "Share Usage Data" toggle to the backend's
            # server-side ws-connect/agent telemetry. Guarded: an
            # analytics failure must never block the connection.
            try:
                from mixar.modules.common.analytics.preferences import (
                    is_enabled as _telemetry_enabled,
                )
                headers.append(
                    f"x-telemetry-consent: {'1' if _telemetry_enabled() else '0'}"
                )
            except Exception:
                pass

            if not token:
                logger.warning("No auth token available - connection may fail")

            self._ws = websocket.create_connection(
                self.ws_url, timeout=10, header=headers
            )
            self._connected = True

            # Perform handshake. The backoff delay and auth-failure counter
            # are only reset AFTER the handshake succeeds: resetting them on
            # bare TCP/WS connect meant a server that accepts the upgrade but
            # rejects the token was retried in a tight ~1s loop forever
            # (failure count wiped each cycle, so max_failures never tripped).
            outcome = self._perform_handshake()
            if outcome != HANDSHAKE_OK:
                try:
                    self._ws.close()
                except Exception:
                    pass
                self._connected = False
                if outcome == HANDSHAKE_AUTH_FAILED:
                    # The server said so explicitly (close 4001 or a
                    # NOT_AUTHENTICATED reply). A timeout or any other
                    # close is NOT counted: it used to be, and three of
                    # them during a backend restart stopped the loop for
                    # good.
                    self._auth.record_failure(token)
                    self._current_delay = self._auth.retry_delay(
                        self._current_delay
                    )
                    logger.warning(
                        f"Handshake rejected (auth), attempt "
                        f"{self._auth.failure_count}; retrying in "
                        f"{self._current_delay:.0f}s after a token refresh"
                    )
                return False

            self._handshake_complete = True
            if self._archive_sync:
                self._archive_sync.stop()
                self._archive_sync = None
            if self.agent_history_supported:
                from ...common.agent_history.core.sync import ArchiveSync
                self._archive_sync = ArchiveSync(self)
                self._archive_sync.start()
            self._current_delay = self._reconnect_delay
            self._auth.reset()
            self._last_ping_time = time.time()
            self._last_recv_time = time.time()
            self._liveness_probe_started = None

            self._ws.settimeout(10.0)
            from .socket_writer import start_writer
            self._writer = start_writer(self)
            from .socket_reauth import start_reauth
            self._reauth_stop = start_reauth(self, token)
            if self._on_connected:
                try:
                    self._on_connected()
                except Exception as e:
                    logger.error(f"Error in on_connected callback: {e}")

            logger.info("JSON-RPC WebSocket connected and authenticated")
            return True

        except websocket.WebSocketException as e:
            # ``status_code`` is the HTTP status of a refused upgrade. Only
            # 401/403 mean the credentials were rejected; a 502/503 from the
            # load balancer while the backend is down is a plain retry.
            status_code = getattr(e, 'status_code', None)
            if status_code in (401, 403):
                self._auth.record_failure(token)
                self._current_delay = self._auth.retry_delay(self._current_delay)
                logger.error(
                    f"WebSocket upgrade refused with HTTP {status_code}, "
                    f"auth attempt {self._auth.failure_count}: {e}"
                )
                self._connected = False
                return False
            logger.warning(f"Connection failed: {e}")
            self._connected = False
            return False
        except Exception as e:
            logger.warning(f"Connection failed: {e}")
            self._connected = False
            return False

    def _try_refresh_token(self) -> tuple[Optional[str], bool]:
        """Attempt to refresh the access token.

        Returns ``(new_token_or_None, retryable)``. ``retryable`` is False
        only when the refresh itself was rejected (401/403 — the tokens are
        deleted by then) or there is no refresh token: a later attempt can
        never succeed without a new login. A transport error or 5xx keeps
        it True — the backend may simply not be back yet.
        """
        try:
            from ...auth.core.auth import refresh_access_token, get_access_token
            result = refresh_access_token()
            if result.get("success"):
                logger.info("Token refreshed successfully before reconnect")
                return get_access_token(), True
            retryable = bool(result.get("retryable", True))
            logger.warning(
                f"Token refresh failed: {result.get('message')} "
                f"(retryable={retryable})"
            )
            return None, retryable
        except Exception as e:
            logger.warning(f"Token refresh error: {e}")
        return None, True

    def _perform_handshake(self) -> str:
        """Send the handshake and wait for the reply.

        Returns a HANDSHAKE_* outcome. Only HANDSHAKE_AUTH_FAILED counts
        toward the auth backoff; a timeout, a non-4001 close or a malformed
        reply is HANDSHAKE_TRANSIENT and just retries (jsonrpc_frames).
        """
        from ...addon_project.constants import CAPABILITY as ADDON_PROJECT_CAPABILITY
        from .machine_info import machine_block

        request_id = f"handshake_{self._next_request_id()}"

        params = {
            "blender_version": self._blender_version,
            "addon_version": self._addon_version,
            # "local_llm": this client can execute llm.request relays against
            # a local model server (modules/local_models) — the backend only
            # sends them when the user's BYOK provider is "local".
            "capabilities": [
                "agent_history_v1",
                # Image bytes by HTTP reference; sync frames stay small.
                "agent_history_v2",
                "script_execution",
                "notifications",
                "local_llm",
                # Client answers blender.liveness on the WS thread; the
                # backend only probes instances that advertise it (older
                # clients would silently never reply).
                "liveness",
                ADDON_PROJECT_CAPABILITY,
                # blender.execute_script frames may carry params["envelope"]
                # (harness v3 task envelope); this client parses and carries
                # it. Task ADMISSION on it is negotiated by later capabilities.
                "exec_envelope_v3",
                # Harness v3 execution protocol bundle (agent.execution.*):
                # task bindings, operation receipts (SQLite journal), native
                # artifact append, document epoch, runtime question routing.
                "task_binding_v1",
                "operation_receipts_v1",
                "native_artifacts_v1",
                "document_epoch_v1",
                "runtime_questions_v1",
            ],
            # Physical resources of THIS machine. The backend sizes the agent's
            # scene geometry budget from it (a Cycles render of a scene that
            # outgrew the RAM is what the OS kills); a client that omits it is
            # assumed to be a 16 GB machine.
            "machine": machine_block(),
        }
        # Anti-abuse device signal (one trial per machine); best-effort
        if self._device_id:
            params["device_id"] = self._device_id
        # A headless sandbox identifies itself so the backend can route a
        # create_model sub-build to it (parent_instance_id -> this connection).
        if self._role:
            params["role"] = self._role
            params["parent_instance_id"] = self._parent_instance_id
        handshake = {
            "jsonrpc": "2.0",
            "method": JSONRPCMethod.SYSTEM_HANDSHAKE,
            "id": request_id,
            "params": params,
        }

        self.agent_ws_supported = False
        self.agent_history_supported = False
        self.agent_history_blobs_by_reference = False
        self._ws.send(json.dumps(handshake))

        try:
            outcome, detail = wait_for_handshake(
                self._ws, timeout=10.0,
                result_sink=self._set_server_capabilities,
            )
        except Exception as e:
            logger.warning(f"Handshake error: {e} - transient, will retry")
            return HANDSHAKE_TRANSIENT
        if outcome == HANDSHAKE_OK:
            logger.info("Handshake successful")
        elif outcome == HANDSHAKE_AUTH_FAILED:
            logger.error(f"Handshake rejected: {detail}")
        else:
            logger.warning(f"Handshake not answered: {detail} - will retry")
        return outcome

    def _set_server_capabilities(self, result):
        self.agent_ws_supported = bool(result.get('agent_ws_v1'))
        capabilities = result.get('server_capabilities', [])
        self.agent_history_supported = 'agent_history_v1' in capabilities
        self.agent_history_blobs_by_reference = 'agent_history_v2' in capabilities
