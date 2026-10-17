# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Chat images go up over HTTP before the command that names them.

The image used to ride the agent socket inside the chat frame (base64, a few
hundred KB): pings and tool replies queued behind it on a slow uplink, and a
frame lost with a dead socket had to go again in full (prod 2026-10-15). When
the server advertises ``agent_attachments_v1``, each image is first sent to
``POST /api/v1/agent/attachments`` and the command carries
``{"type": "image_ref", "image_ref": {"id": ...}}`` instead — a frame of a
few hundred bytes. The server stores the bytes in the session's image store
(content-addressed: the same image always gets the same id) and turns each
reference back into the data URL before moderation, so nothing downstream
changes (mixar-backend docs/api/frontend/agent-attachments.md).

Any upload failure keeps the images inline: never worse than before.
"""
import base64
import re
import threading
import time

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

CAPABILITY = 'agent_attachments_v1'
ENDPOINT = 'api/v1/agent/attachments'
REF_TYPE = 'image_ref'
UNAVAILABLE = 'attachment_unavailable'
# One deadline for a message's uploads: a base plus the time its bytes need
# at 16 KB/s, capped. Past it the images go inline instead — a silently dead
# path must not hold the message for minutes.
UPLOAD_BASE_S = 20.0
UPLOAD_MIN_BPS = 16_000
UPLOAD_MAX_S = 180.0
_FIELDS = {'chat': 'content', 'input': 'attachments'}
_DATA_URL = re.compile(r'^data:(image/[\w.+-]+);base64,(.*)$', re.S)


def server_supports():
    from .jsonrpc_client import get_jsonrpc_client
    client = get_jsonrpc_client()
    return bool(client is not None and getattr(client, 'agent_attachments_by_reference', False))


def _inline_images(method, payload):
    """``(field, index, mime, raw)`` for every inline data-URL image block."""
    field = _FIELDS.get(method)
    blocks = payload.get(field) if field else None
    found = []
    for index, block in enumerate(blocks if isinstance(blocks, list) else ()):
        if not (isinstance(block, dict) and block.get('type') == 'image_url'):
            continue
        match = _DATA_URL.match(str((block.get('image_url') or {}).get('url') or ''))
        if match:
            found.append((field, index, match.group(1), match.group(2)))
    return found


def wanted(method, payload):
    return bool(_inline_images(method, payload)) and server_supports()


_client = None


def _http():
    """Uploads never retry: the shared client retries a POST three times,
    which on a stalled path held the message for minutes before the inline
    fallback. One attempt, one deadline; a failure goes inline."""
    global _client
    if _client is None:
        from mixar.modules.common.api.client import HTTPClient
        _client = HTTPClient(retry_count=0)
    return _client


def upload(session_id, b64, timeout):
    """One image's id on the server. Worker thread; raises on any failure.
    The server reads the type from the bytes."""
    response = _http().post(ENDPOINT, params={'session_id': session_id},
                            data=base64.b64decode(b64), timeout=timeout)
    data = getattr(response, 'data', None)
    image_id = ((data or {}).get('data') or {}).get('id') if isinstance(data, dict) else None
    if not isinstance(image_id, str) or not image_id:
        raise ValueError('attachment upload returned no id')
    return image_id


def offload(method, payload, then):
    """Upload ``payload``'s inline images on a worker thread, swap them for
    references in place, then call ``then()`` on the main thread.

    Returns the inline blocks it replaced as ``{field: [blocks]}`` (a copy
    taken before the swap) so the caller can send them again inline if the
    server ever answers ``attachment_unavailable``; the swap itself happens
    only after every upload succeeded."""
    images = _inline_images(method, payload)
    backup = {field: list(payload[field]) for field in {item[0] for item in images}}
    session_id = payload.get('session_id') or ''

    def work():
        started = time.monotonic()
        total = sum(len(b64) * 3 // 4 for _f, _i, _m, b64 in images)
        deadline = started + min(UPLOAD_MAX_S, UPLOAD_BASE_S + total / UPLOAD_MIN_BPS)
        ids, failure = {}, None
        try:
            for field, index, mime, b64 in images:
                key = (mime, b64)  # the same picture twice is one upload
                if key not in ids:
                    left = deadline - time.monotonic()
                    if left <= 0:
                        raise TimeoutError('attachment upload deadline passed')
                    ids[key] = upload(session_id, b64, left)
        except Exception as exc:  # noqa: BLE001 — any failure: the images stay inline
            failure = exc
        from mixar.modules.byok.core.byok_client import schedule_on_main
        schedule_on_main(_swap, ids, failure, time.monotonic() - started)

    def _swap(ids, failure, took):
        if failure is None:
            for field, index, mime, b64 in images:
                block = payload[field][index]
                ref = {'type': REF_TYPE, 'image_ref': {'id': ids[(mime, b64)]}}
                if block.get('name'):
                    ref['name'] = block['name']
                payload[field][index] = ref
            logger.info('[CHAT] %d attachment(s) uploaded in %.1fs; the command carries references',
                        len(images), took)
        else:
            logger.warning('[CHAT] attachment upload failed (%s); sending the images inline',
                           type(failure).__name__)
        then()

    threading.Thread(target=work, name='MixarChatAttachmentUpload', daemon=True).start()
    return backup


def restore(payload, backup):
    """Put the inline blocks back (after ``attachment_unavailable``)."""
    for field, blocks in (backup or {}).items():
        payload[field] = list(blocks)


def unavailable(result):
    data = (result or {}).get('data') or {}
    return isinstance(data, dict) and data.get('code') == UNAVAILABLE
