# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Plain-language text for a message the agent never took.

A send that fails is explained by ONE agent message in the chat
(``queue_processor.handle_command_error``), never by a label on the user's
bubble. This module picks that message's words: what happened and what to
do, never an exception, a status code or a stack trace.

- the client gave up resending a message lost with its socket
  (``undelivered``) → :data:`MSG_NOT_DELIVERED`;
- the client could not send it at all (``unsent``, the local RPC raised) →
  by the status the raise carried: :data:`MSG_OFFLINE` for a missing or dead
  socket (503, or an exception with no status), :data:`MSG_UPDATE` for a
  server without the WebSocket agent (426), :data:`MSG_TOO_LARGE` for a
  frame the socket refused (413), :data:`MSG_FAILED` otherwise;
- the server refused it with a sentence written for people → that sentence
  (a provider's ``error.message`` is read out of a raw ``Error code: NNN -
  {…}`` / JSON body first);
- anything technical → :data:`MSG_OFFLINE` when it reads as a connection
  problem, else :data:`MSG_FAILED`.

Pure: no bpy. Main thread or any thread.
"""

import ast
import json
import re

from mixar.modules.common.i18n import n_, rpt_

MSG_NOT_DELIVERED = n_("Your message didn't reach Mixie. Check your connection, then send it again.")
# Both msgids already exist (shared with the stream-error path and the BYOK
# client), so their translations are reused.
MSG_OFFLINE = n_("Couldn't reach the server. Please check your connection and try again.")
MSG_FAILED = n_("Something went wrong on our end. Please try again.")
MSG_UPDATE = n_("This version of Mixar and the server don't match. Update Mixar, then try again.")
MSG_TOO_LARGE = n_("Your message is too large to send. Remove some attachments or shorten it, "
                   "then try again.")
# The status an unsent command's raise carried → its words; None is a dead
# socket's non-AgentRPCError (agent_rpc/client.py raises the rest).
_UNSENT_TEXT = {None: MSG_OFFLINE, 503: MSG_OFFLINE, 426: MSG_UPDATE, 413: MSG_TOO_LARGE}
_PROVIDER_BODY = re.compile(r'^Error code: \d{3} - (\{.*\})\s*$', re.S)

# Texts that name the protocol rather than the problem: server receipts and
# the client's own transport errors (socket_*.py, agent_rpc/client.py).
_TECHNICAL_TEXT = (
    'command id was already used',
    'invalid agent command fields',
    'session unavailable',
    'agent command failed',
    'agent request failed',
    'websocket agent update',
    'delivery is uncertain',
    'operation timed out',
    'connection error:',
    'connection refused',
    'connection reset',
    'agent is reconnecting',
    'connection is busy',
)
# Which fallback a technical text gets.
_CONNECTION_WORDS = ('timed out', 'connection', 'reconnect', 'socket', 'unreachable', 'network')
_EXCEPTION_NAME = re.compile(r'^\s*[A-Za-z_][\w.]*(Error|Exception)\b')


def refusal_text(result) -> str:
    """The agent message for a refused (or never sent) command result."""
    result = result if isinstance(result, dict) else {}
    if result.get('undelivered'):
        return rpt_(MSG_NOT_DELIVERED)
    if result.get('unsent'):
        return rpt_(_UNSENT_TEXT.get(result.get('status_code'), MSG_FAILED))
    return plain_text(result.get('message') or '')


def plain_text(message: str) -> str:
    """``message`` when a person can read it, else the friendly fallback."""
    text = _provider_message(_http_body_message(str(message or '').strip()))
    if not text:
        return rpt_(MSG_FAILED)
    if not _technical(text):
        return text
    lowered = text.lower()
    if any(word in lowered for word in _CONNECTION_WORDS):
        return rpt_(MSG_OFFLINE)
    return rpt_(MSG_FAILED)


def _http_body_message(text: str) -> str:
    """``HTTP 4xx: {"message": …}`` → the body's message; other text as is."""
    if not text.startswith('HTTP '):
        return text
    _, _, body = text.partition(': ')
    try:
        data = json.loads(body)
    except (TypeError, ValueError):
        return text
    if isinstance(data, dict):
        inner = data.get('detail') if isinstance(data.get('detail'), dict) else data
        if isinstance(inner, dict) and isinstance(inner.get('message'), str):
            return inner['message'].strip()
    return text


def _provider_message(text: str) -> str:
    """A provider SDK's raw error (``Error code: 429 - {'error': {'message':
    …}}``, or a bare JSON body) → its ``error.message``; other text as is.
    The result still has to pass the technical filter."""
    match = _PROVIDER_BODY.match(text)
    body = match.group(1) if match else text if text.startswith('{') else ''
    if not body:
        return text
    for parse in (json.loads, ast.literal_eval):  # JSON, or the SDK's dict repr
        try:
            data = parse(body)
            break
        except (TypeError, ValueError, SyntaxError, MemoryError, RecursionError):
            data = None
    inner = data.get('error') if isinstance(data, dict) else None
    inner = inner if isinstance(inner, dict) else data
    if isinstance(inner, dict) and isinstance(inner.get('message'), str) and inner['message'].strip():
        return inner['message'].strip()
    return text


def _technical(text: str) -> bool:
    lowered = text.lower()
    return (
        text.startswith('HTTP ')
        or 'traceback' in lowered
        or 'file "' in lowered
        or '{' in text
        or '[errno' in lowered
        or bool(_EXCEPTION_NAME.match(text))
        or any(marker in lowered for marker in _TECHNICAL_TEXT)
    )
