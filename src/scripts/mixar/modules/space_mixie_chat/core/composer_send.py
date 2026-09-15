# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""How a composed user message leaves the client — ONE choice point.

The chat is never blocked while the agent works. A backend run spans turns
(``SessionManager.set_run``), so a message typed while the orchestrator is
busy JOINS the run instead of being refused — exactly like typing while
Claude Code / Codex is working:

- IDLE (run open or not) / MODIFYING / AWAITING_INPUT → the existing SSE
  paths (``/agent/chat`` fresh turn, or ``/agent/input`` answer). With the
  run open, the backend continues the same run inline.
- BUSY with the run open → an *interjection*: ``POST /agent/chat`` with the
  normal body on a worker thread; the response's FIRST payload is the
  ``joined`` ack, after which the response is closed — the live SSE stream
  or the socket already delivers the turn's events. ``create_sse_handler`` is
  never called here: it would kill the stream that is rendering the turn.
- BUSY with no run open → refused with a reason (older backend, or the
  first ``run_status`` has not arrived yet).

The coming WebSocket-only transport replaces ``send_user_message``.
"""

import json
import threading
from dataclasses import dataclass
from typing import Optional

from mixar.config.config import get_server_url
from mixar.config.logging_config import get_logger

from ..constants import AGENT_CHAT_ENDPOINT, STATE_LABELS, SessionState
from .session import get_session_manager

logger = get_logger(__name__)

HINT_QUEUED = "queued"
HINT_UNDELIVERED = "could not be delivered"
_BUSY_REASON = "Mixie is still working on the previous message"


@dataclass
class OutgoingMessage:
    """What the composer assembled; ``text`` is the raw user text (the wire
    message gets the project rules prepended in ``send_user_message``)."""
    text: str
    image_attachments: Optional[list] = None
    attachment_names: Optional[list] = None
    imported_object_names: Optional[list] = None
    project_context: Optional[dict] = None
    mark_context: Optional[dict] = None


# ---------------------------------------------------------------------------
# Predicates (operator poll, Enter handler, quick prompt)
# ---------------------------------------------------------------------------


def can_send(scene) -> tuple[bool, str]:
    """(allowed, reason). Allowed: IDLE / MODIFYING / AWAITING_INPUT, and
    BUSY while the run is open (the message joins the run)."""
    session = get_session_manager()
    state = session.get_state(scene)
    if state in (SessionState.IDLE, SessionState.MODIFYING, SessionState.AWAITING_INPUT):
        return True, ""
    if state == SessionState.BUSY:
        if session.run_open(scene):
            return True, ""
        return False, _BUSY_REASON
    return False, STATE_LABELS.get(state, "Mixie Chat is not connected")


def is_interjection(scene) -> bool:
    """True when a send right now joins a turn that is still streaming."""
    session = get_session_manager()
    return session.get_state(scene) == SessionState.BUSY and session.run_open(scene)


# ---------------------------------------------------------------------------
# The choice point
# ---------------------------------------------------------------------------


def send_user_message(scene, msg: OutgoingMessage) -> tuple[bool, str]:
    """Dispatch ``msg`` for ``scene``. Returns (ok, error_message).

    Owns the session-state bookkeeping of each route so the operator only
    reports the outcome.
    """
    session = get_session_manager()
    state = session.get_state(scene)
    if state in (SessionState.MODIFYING, SessionState.AWAITING_INPUT):
        return _send_input(scene, session, state, msg)
    if state == SessionState.BUSY:
        if session.run_open(scene):
            return _send_interjection(scene, session, msg)
        return False, _BUSY_REASON
    return _send_new_turn(scene, session, msg)


def _handler_for(scene):
    """A fresh per-scene SSE handler wired to the main-thread queue."""
    from .queue_processor import queue_sse_complete, queue_sse_error, queue_sse_event
    from .sse_handler import create_sse_handler

    scene_name = scene.name
    return create_sse_handler(
        scene_name=scene_name,
        host=get_server_url(),
        on_event=lambda event: queue_sse_event(event, scene_name),
        on_error=lambda error: queue_sse_error(error, scene_name),
        on_complete=lambda: queue_sse_complete(scene_name),
    )


def _send_input(scene, session, state, msg: OutgoingMessage) -> tuple[bool, str]:
    """Modify feedback or the answer to a pending question → /agent/input."""
    from .message_helpers import get_auth_token
    from .question_ref import pending_question_ref

    handler = _handler_for(scene)
    ok = handler.start_input_stream(
        session_id=session.get_session_id(scene),
        action="modify" if state == SessionState.MODIFYING else "respond",
        text=msg.text,
        auth_token=get_auth_token(),
        question_ref=pending_question_ref(scene),
    )
    if not ok:
        session.set_state(scene, SessionState.IDLE)  # Return to idle on error
        return False, "Failed to send input"
    session.set_state(scene, SessionState.BUSY)  # Set to busy after sending
    session.clear_streaming()
    return True, ""


def _send_new_turn(scene, session, msg: OutgoingMessage) -> tuple[bool, str]:
    """A fresh SSE turn (with the run open, the backend continues it inline)."""
    from .jsonrpc_client import get_jsonrpc_client
    from .message_helpers import get_auth_token
    from .rules import compose_wire_message, mark_rules_sent

    ws_client = get_jsonrpc_client()
    if ws_client is None or not ws_client.connection_id:
        return False, "Not connected to server"

    # Compose the wire message BEFORE start_session — project rules are
    # prepended only when this send opens a NEW session, and start_session
    # is what generates the session id.
    wire_message = compose_wire_message(scene, msg.text)
    session_id = session.start_session(scene, msg.text)
    handler = _handler_for(scene)
    ok = handler.start_stream(
        message=wire_message,
        instance_id=ws_client.connection_id,
        session_id=session_id,
        plan_required=getattr(scene, 'mixie_chat_plan_enabled', True),
        execution_required=True,
        approval_required=True,
        auth_token=get_auth_token(),
        image_attachments=msg.image_attachments or None,
        attachment_names=msg.attachment_names or None,
        imported_object_names=msg.imported_object_names or None,
        project_context=msg.project_context,
        mark_context=msg.mark_context,
    )
    if not ok:
        session.set_error(scene)
        return False, "Failed to start chat stream"
    # Stamp the rules fingerprint only after the send succeeded so a failed
    # start never swallows a pending update.
    mark_rules_sent(scene)
    return True, ""


def _send_interjection(scene, session, msg: OutgoingMessage) -> tuple[bool, str]:
    """Join the streaming turn: POST the normal body, keep only the ack."""
    from .jsonrpc_client import get_jsonrpc_client
    from .message_helpers import get_auth_token
    from .rules import compose_wire_message, mark_rules_sent
    from .sse_handler import build_chat_payload, collect_user_preferences

    ws_client = get_jsonrpc_client()
    if ws_client is None or not ws_client.connection_id:
        return False, "Not connected to server"

    payload = build_chat_payload(
        message=compose_wire_message(scene, msg.text),
        instance_id=ws_client.connection_id,
        session_id=session.get_session_id(scene),
        plan_required=getattr(scene, 'mixie_chat_plan_enabled', True),
        execution_required=True,
        approval_required=True,
        image_attachments=msg.image_attachments or None,
        attachment_names=msg.attachment_names or None,
        imported_object_names=msg.imported_object_names or None,
        project_context=msg.project_context,
        mark_context=msg.mark_context,
        user_preferences=collect_user_preferences(),
    )
    threading.Thread(
        target=_interjection_body,
        args=(scene.name, f"{get_server_url()}{AGENT_CHAT_ENDPOINT}", payload, get_auth_token()),
        daemon=True,
        name="MixarInterjection",
    ).start()
    mark_rules_sent(scene)
    return True, ""


# ---------------------------------------------------------------------------
# Interjection worker (background thread — never touches bpy)
# ---------------------------------------------------------------------------


def _interjection_body(scene_name: str, url: str, payload: dict, auth_token: str) -> None:
    """POST, read the first SSE payload, close. Outcome goes through the
    inbound queue so the user bubble's hint settles on the main thread."""
    from .queue_processor import queue_sse_event
    from .sse_handler import SSEEvent, _base_headers, _try_refresh_token, httpx

    ack: Optional[dict] = None
    error = ""
    try:
        if httpx is None:
            raise RuntimeError("httpx library not available")
        headers = _base_headers(auth_token)
        timeout = httpx.Timeout(connect=10.0, read=30.0, write=60.0, pool=10.0)
        with httpx.Client(timeout=timeout) as client:
            ack, error = _post_for_ack(client, url, payload, headers)
            if error == "401":
                new_token = _try_refresh_token()
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    ack, error = _post_for_ack(client, url, payload, headers)
    except Exception as e:  # noqa: BLE001 — reported on the bubble below
        error = str(e)

    if isinstance(ack, dict) and ack.get("type") == "joined":
        logger.info(
            "interjection joined run %s (queued=%s)",
            str(ack.get("run_id") or "")[:8], ack.get("queued"),
        )
        queue_sse_event(SSEEvent(event_type="joined", data=ack), scene_name)
        return

    if not error:
        error = f"unexpected first payload type={ack.get('type') if isinstance(ack, dict) else None}"
    logger.error("interjection was not joined: %s", error)
    queue_sse_event(
        SSEEvent(event_type="interjection_failed",
                 data={"type": "interjection_failed", "reason": error}),
        scene_name,
    )


def _post_for_ack(client, url: str, payload: dict, headers: dict) -> tuple[Optional[dict], str]:
    """One POST; returns (first payload, error). Closes the response on exit."""
    with client.stream("POST", url, json=payload, headers=headers) as response:
        if response.status_code == 401:
            response.read()
            return None, "401"
        if response.status_code != 200:
            text = ""
            try:
                text = response.read().decode()[:200]
            except Exception:  # noqa: BLE001
                pass
            return None, f"HTTP {response.status_code}: {text}"
        for line in response.iter_lines():
            if not line or not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str == "[DONE]":
                return None, "stream ended before the joined ack"
            try:
                return json.loads(data_str), ""
            except json.JSONDecodeError:
                return None, "invalid ack payload"
    return None, "no ack received"


# ---------------------------------------------------------------------------
# Main thread: the user bubble's delivery hint
# ---------------------------------------------------------------------------


def on_interjection_ack(scene, data: dict) -> None:
    """``joined`` clears the oldest queued hint; a failure marks it undelivered.

    Acks come back in send order, so the oldest queued USER bubble is the one
    this ack answers.
    """
    messages = getattr(scene, "mixie_chat_messages", None)
    if not messages:
        return
    for msg in messages:
        if msg.sender != 'USER' or getattr(msg, 'delivery_hint', '') != HINT_QUEUED:
            continue
        msg.delivery_hint = "" if data.get("type") == "joined" else HINT_UNDELIVERED
        return
