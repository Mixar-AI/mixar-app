# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""
SSE (Server-Sent Events) handler for /blender/agent/chat and /agent/input endpoints.

Uses httpx for HTTP/SSE streaming.
"""

import json
from mixar.config.logging_config import get_logger
import threading
from dataclasses import dataclass
from typing import Callable, Optional

from ..constants import (
    AGENT_CHAT_ENDPOINT,
    AGENT_INPUT_ENDPOINT,
    SSE_READ_TIMEOUT
)

try:
    import httpx
except ImportError:
    httpx = None

logger = get_logger(__name__)


def _try_refresh_token() -> str:
    """Attempt to refresh the access token and return the new token.

    Returns:
        New access token string, or empty string if refresh failed.
    """
    try:
        from mixar.modules.auth.core.auth import refresh_access_token, get_access_token
        result = refresh_access_token()
        if result.get("success"):
            logger.info("Token refreshed successfully in SSE handler")
            return get_access_token() or ""
    except Exception as e:
        logger.warning(f"Token refresh failed in SSE handler: {e}")
    return ""


@dataclass
class SSEEvent:
    """Parsed SSE event."""
    event_type: str
    data: dict


class SSEStreamHandler:
    """
    Handles SSE streaming from /blender/agent/chat and /agent/input endpoints.

    Runs in a background thread and calls the event callback
    for each received event.
    """

    def __init__(
        self,
        host: str,
        on_event: Callable[[SSEEvent], None],
        on_error: Callable[[str], None],
        on_complete: Callable[[], None],
    ):
        self._host = host
        self._on_event = on_event
        self._on_error_cb = on_error
        self._on_complete = on_complete

        self._thread: Optional[threading.Thread] = None
        self._running = threading.Event()
        self._client: Optional["httpx.Client"] = None
        self._user_aborted = False

    def _on_error(self, message: str) -> None:
        if self._user_aborted:
            logger.debug(f"Suppressing SSE error after user abort: {message}")
            return
        self._on_error_cb(message)

    @property
    def chat_url(self) -> str:
        """Build chat endpoint URL."""
        return f"{self._host}{AGENT_CHAT_ENDPOINT}"

    @property
    def input_url(self) -> str:
        """Build input endpoint URL."""
        return f"{self._host}{AGENT_INPUT_ENDPOINT}"

    @property
    def is_running(self) -> bool:
        """Check if stream is currently running."""
        return self._running.is_set()

    def start_stream(
        self,
        message: str,
        instance_id: str,
        session_id: str,
        plan_required: bool = False,
        execution_required: bool = False,
        approval_required: bool = True,
        auth_token: Optional[str] = None,
        image_attachments: Optional[list] = None,
        attachment_names: Optional[list] = None,
    ) -> bool:
        """
        Start SSE stream for V2 agent chat.

        Args:
            message: User's chat message
            instance_id: Connection ID for WebSocket
            session_id: Unique session identifier
            plan_required: Whether planning is required (True for PLAN/AGENT mode)
            execution_required: Whether execution is required (True for PLAN/AGENT mode)
            approval_required: Whether approval is required before execution
            auth_token: Optional auth token for request
            image_attachments: Pre-encoded image attachments as list of dicts:
                [{"base64": str, "mime_type": str}, ...]
            attachment_names: bpy.data.images names parallel to image_attachments
                (entries may be empty string when an attachment could not be
                resolved to a bpy.data.images entry). Sent to the backend so it
                can inline the names into the user message and the agent can
                pass them straight to generation tools without a tool round-trip.

        Returns:
            True if stream started successfully
        """
        if httpx is None:
            self._on_error("httpx library not available")
            return False

        if self._running.is_set():
            logger.warning("Stream already running")
            return False

        self._user_aborted = False
        self._running.set()
        self._thread = threading.Thread(
            target=self._stream_loop,
            args=(message, instance_id, session_id, plan_required, execution_required, approval_required, auth_token, image_attachments, attachment_names),
            daemon=True,
        )
        self._thread.name = "MixarSSEStream"
        self._thread.start()

        return True

    def stop_stream(self) -> None:
        """Stop the SSE stream."""
        self._user_aborted = True
        self._running.clear()
        if self._client:
            try:
                self._client.close()
            except Exception:
                pass

    def start_input_stream(
        self,
        session_id: str,
        action: str,
        text: str = "",
        auth_token: Optional[str] = None,
    ) -> bool:
        """
        Start SSE stream for input request (unified interrupt response).

        Args:
            session_id: Session ID for the input
            action: Action type ("approve", "modify", "abort", "retry", "submit", or custom)
            text: Optional text payload (used with "modify", "submit")
            auth_token: Optional auth token for request

        Returns:
            True if stream started successfully
        """
        if httpx is None:
            self._on_error("httpx library not available")
            return False

        if self._running.is_set():
            logger.warning("Stream already running")
            return False

        self._user_aborted = False
        self._running.set()
        self._thread = threading.Thread(
            target=self._input_stream_loop,
            args=(session_id, action, text, auth_token),
            daemon=True,
        )
        self._thread.name = "MixarInputStream"
        self._thread.start()

        logger.info(f"Input stream started: action={action} for session {session_id[:8]}...")
        return True

    def _input_stream_loop(
        self,
        session_id: str,
        action: str,
        text: str,
        auth_token: Optional[str],
    ) -> None:
        """Background thread that handles input SSE streaming."""
        received_done = False
        try:
            headers = {"Accept": "text/event-stream"}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

            payload = {
                "session_id": session_id,
                "action": action,
                "text": text,
            }

            logger.debug(f"Starting input SSE request to {self.input_url}")

            timeout_config = httpx.Timeout(
                connect=10.0,
                read=SSE_READ_TIMEOUT,
                write=60.0,
                pool=10.0,
            )

            self._client = httpx.Client(timeout=timeout_config)
            try:
                with self._client.stream(
                    "POST",
                    self.input_url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code == 401:
                        response.read()
                        logger.debug("Got 401 on input stream, attempting token refresh")
                        new_token = _try_refresh_token()
                        if new_token:
                            headers["Authorization"] = f"Bearer {new_token}"
                        else:
                            self._on_error(f"HTTP 401: {response.text}")
                            return
                    elif response.status_code != 200:
                        error_text = ""
                        try:
                            error_text = response.read().decode()
                        except Exception:
                            pass
                        self._on_error(f"HTTP {response.status_code}: {error_text}")
                        return
                    else:
                        # 200 — process stream and return
                        received_done = self._consume_sse_stream(response, "Input")
                        if not received_done:
                            self._on_error("Server closed the connection unexpectedly")
                        return

                # Retry after token refresh (only reached on 401 with successful refresh)
                self._client.close()
                self._client = httpx.Client(timeout=timeout_config)
                with self._client.stream(
                    "POST",
                    self.input_url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = ""
                        try:
                            error_text = response.read().decode()
                        except Exception:
                            pass
                        self._on_error(f"HTTP {response.status_code}: {error_text}")
                        return

                    received_done = self._consume_sse_stream(response, "Input")
                    if not received_done:
                        self._on_error("Server closed the connection unexpectedly")

            finally:
                self._client.close()
                self._client = None

        except httpx.ConnectError as e:
            self._on_error(f"Connection error: {e}")
        except httpx.TimeoutException as e:
            logger.error(f"Input SSE read timeout after {SSE_READ_TIMEOUT}s: {e}")
            self._on_error(f"Request timeout: {e}")
        except Exception as e:
            logger.error(f"Input stream error: {e}")
            self._on_error(str(e))
        finally:
            self._running.clear()

    def _stream_loop(
        self,
        message: str,
        instance_id: str,
        session_id: str,
        plan_required: bool,
        execution_required: bool,
        approval_required: bool,
        auth_token: Optional[str],
        image_attachments: Optional[list] = None,
        attachment_names: Optional[list] = None,
    ) -> None:
        """Background thread that handles V2 SSE streaming."""
        try:
            headers = {"Accept": "text/event-stream"}
            if auth_token:
                headers["Authorization"] = f"Bearer {auth_token}"

            # Build multimodal content payload
            content = [{"type": "text", "text": message}]
            if image_attachments:
                for img in image_attachments:
                    mime = img.get("mime_type", "image/png")
                    b64 = img.get("base64", "")
                    content.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    })

            payload = {
                "message": message,
                "instance_id": instance_id,
                "session_id": session_id,
                "plan_required": plan_required,
                "execution_required": execution_required,
                "approval_required": approval_required,
            }

            # Add multimodal content if there are image attachments
            if image_attachments and len(content) > 1:
                payload["content"] = content

            # Forward resolved bpy.data.images names so the backend can inline
            # them into the user message; entries are positional and may be
            # empty strings when an attachment did not resolve to a name.
            if attachment_names:
                payload["attachment_names"] = [n for n in attachment_names if n]

            logger.debug(f"Starting SSE request to {self.chat_url}")

            # Per-phase timeouts. read=SSE_READ_TIMEOUT must exceed the
            # backend's 600s tool timeout to avoid a client-side race.
            # write must accommodate large multimodal payloads (base64
            # images can be several MB) on slow connections.
            timeout_config = httpx.Timeout(
                connect=10.0,
                read=SSE_READ_TIMEOUT,
                write=60.0,
                pool=10.0,
            )

            self._client = httpx.Client(timeout=timeout_config)
            try:
                with self._client.stream(
                    "POST",
                    self.chat_url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code == 401:
                        response.read()
                        logger.debug("Got 401 on chat stream, attempting token refresh")
                        new_token = _try_refresh_token()
                        if new_token:
                            headers["Authorization"] = f"Bearer {new_token}"
                        else:
                            self._on_error(f"HTTP 401: {response.text}")
                            return
                    elif response.status_code != 200:
                        error_text = ""
                        try:
                            error_text = response.read().decode()
                        except Exception:
                            pass
                        self._on_error(f"HTTP {response.status_code}: {error_text}")
                        return
                    else:
                        # 200 — process stream and return
                        received_done = self._consume_sse_stream(response, "Chat")
                        if not received_done:
                            self._on_error("Server closed the connection unexpectedly")
                        return

                # Retry after token refresh (only reached on 401 with successful refresh)
                self._client.close()
                self._client = httpx.Client(timeout=timeout_config)
                with self._client.stream(
                    "POST",
                    self.chat_url,
                    json=payload,
                    headers=headers,
                ) as response:
                    if response.status_code != 200:
                        error_text = ""
                        try:
                            error_text = response.read().decode()
                        except Exception:
                            pass
                        self._on_error(f"HTTP {response.status_code}: {error_text}")
                        return

                    received_done = self._consume_sse_stream(response, "Chat")
                    if not received_done:
                        self._on_error("Server closed the connection unexpectedly")

            finally:
                self._client.close()
                self._client = None

        except httpx.ConnectError as e:
            self._on_error(f"Connection error: {e}")
        except httpx.TimeoutException as e:
            self._on_error(f"Request timeout: {e}")
        except Exception as e:
            logger.error(f"SSE stream error: {e}")
            self._on_error(str(e))
        finally:
            self._running.clear()

    def _consume_sse_stream(self, response, label: str = "SSE") -> bool:
        """Iterate over an SSE response, dispatching events.

        Args:
            response: An open httpx streaming response.
            label: Label for log messages (e.g. "Chat", "Input").

        Returns:
            True if the stream completed with a [DONE] marker.
        """
        received_done = False
        try:
            for line in response.iter_lines():
                if not self._running.is_set():
                    logger.debug(f"{label} stream stopped by client")
                    return True  # treat client-stop as graceful

                if not line:
                    continue

                if self._process_sse_line(line):
                    received_done = True
                    break
        except Exception as e:
            logger.error(f"{label} SSE iteration error: {e}")
            self._on_error(str(e))
            return True  # error already reported

        if not received_done:
            logger.warning(f"{label} SSE stream ended without [DONE] marker")
        return received_done

    def _process_sse_line(self, line: str) -> bool:
        """Process a single SSE line.

        Supports two event formats:
        1. Slot-based (new): Has bubble_id field, event_type set to "slot"
        2. Legacy: Has type field, event_type set to that value

        Returns:
            True if [DONE] marker was received, False otherwise.
        """
        if not line.startswith("data: "):
            return False

        data_str = line[6:]  # Remove "data: " prefix

        # Check for [DONE] marker
        if data_str == "[DONE]":
            self._on_complete()
            return True

        try:
            event_data = json.loads(data_str)

            # Detect event format based on presence of bubble_id
            if "bubble_id" in event_data:
                event_type = "slot"
            else:
                # Legacy event-type format
                event_type = event_data.get("type", "unknown")

            event = SSEEvent(event_type=event_type, data=event_data)
            self._on_event(event)
        except json.JSONDecodeError as e:
            logger.warning(f"[SSE] Invalid JSON in SSE line: {e}")

        return False


# Per-scene handler registry: scene_name -> SSEStreamHandler
_sse_handlers: dict[str, SSEStreamHandler] = {}


def get_sse_handler(scene_name: str) -> Optional[SSEStreamHandler]:
    """Get SSE handler for a specific scene.

    Args:
        scene_name: Name of the Blender scene

    Returns:
        SSEStreamHandler for the scene, or None
    """
    return _sse_handlers.get(scene_name)


def create_sse_handler(
    scene_name: str,
    host: str,
    on_event: Callable[[SSEEvent], None],
    on_error: Callable[[str], None],
    on_complete: Callable[[], None],
) -> SSEStreamHandler:
    """
    Create a new SSE handler for a specific scene.

    Stops any existing handler for the same scene (but not other scenes).

    Args:
        scene_name: Name of the Blender scene this handler belongs to
        host: Server host URL
        on_event: Callback for received events
        on_error: Callback for errors
        on_complete: Callback when stream completes

    Returns:
        Created SSEStreamHandler instance
    """
    # Stop existing handler for this scene only
    existing = _sse_handlers.get(scene_name)
    if existing is not None:
        existing.stop_stream()

    handler = SSEStreamHandler(host, on_event, on_error, on_complete)
    _sse_handlers[scene_name] = handler
    return handler


def cleanup_sse_handler(scene_name: str) -> None:
    """Stop and remove the SSE handler for a specific scene.

    Args:
        scene_name: Name of the Blender scene
    """
    handler = _sse_handlers.pop(scene_name, None)
    if handler is not None:
        handler.stop_stream()


def cleanup_all_sse_handlers() -> None:
    """Stop all SSE handlers across all scenes.

    Used by File > Open (load_pre) and module unregister.
    """
    for handler in _sse_handlers.values():
        handler.stop_stream()
    _sse_handlers.clear()
