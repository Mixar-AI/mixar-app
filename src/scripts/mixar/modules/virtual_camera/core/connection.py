# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""One phone's WebSocket: bounded outbound lanes and a dedicated writer thread.

Daemon-thread code; never touches bpy.
"""

from __future__ import annotations

import json
import socket
import threading
from collections import deque

from mixar.config.logging_config import get_logger

from ..constants import JSON_QUEUE_MAX
from . import ws_codec

logger = get_logger(__name__)


class Connection:
    """One WebSocket client with a dedicated writer thread.

    Outbound traffic has three lanes, drained in this order:

    * a bounded queue of JSON messages (toasts, errors) and pongs — at most
      ``JSON_QUEUE_MAX``; when full the oldest is dropped and logged;
    * ONE pending ``state`` message: a newer state replaces a queued one
      (only the latest matters), carrying over a ``settings`` field the
      replaced one had so the phone's first sync is never lost;
    * ONE pending stream frame, overwritten the same way, so a slow phone
      shows a late picture instead of an ever-growing latency queue.
    """

    def __init__(self, sock) -> None:
        self._sock = sock
        self._json_queue: deque[bytes] = deque()
        self._state: dict | None = None
        self._frame: bytes | None = None
        self._dropped = 0
        self._cond = threading.Condition()
        # `_cond` guards the QUEUE; this guards the SOCKET. `close()` writes
        # its frame from the caller's thread while the writer thread may be
        # mid-`sendall` on the same socket, and two interleaved frames are a
        # protocol error the phone cannot resynchronise from.
        self._send_lock = threading.Lock()
        self._alive = True
        self._writer = threading.Thread(
            target=self._write_loop, name="mixar-vcam-writer", daemon=True
        )
        self._writer.start()

    def _enqueue(self, chunk: bytes) -> None:
        """Append to the bounded queue; caller holds ``_cond``."""
        if len(self._json_queue) >= JSON_QUEUE_MAX:
            self._json_queue.popleft()
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 100 == 0:
                logger.warning(
                    "Virtual camera: phone not reading, dropped %d queued "
                    "message(s)", self._dropped,
                )
        self._json_queue.append(chunk)
        self._cond.notify()

    def send_json(self, payload: dict) -> None:
        if payload.get("t") == "state":
            with self._cond:
                if not self._alive:
                    return
                pending = self._state
                if pending is not None and "settings" in pending and "settings" not in payload:
                    payload = {**payload, "settings": pending["settings"]}
                self._state = payload
                self._cond.notify()
            return
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        with self._cond:
            if not self._alive:
                return
            self._enqueue(ws_codec.encode_frame(ws_codec.OP_TEXT, data))

    def send_stream_frame(self, image_bytes: bytes) -> None:
        with self._cond:
            if not self._alive:
                return
            self._frame = ws_codec.encode_frame(ws_codec.OP_BINARY, image_bytes)
            self._cond.notify()

    def send_pong(self, payload: bytes) -> None:
        with self._cond:
            if not self._alive:
                return
            self._enqueue(ws_codec.encode_frame(ws_codec.OP_PONG, payload))

    def pending_counts(self) -> tuple[int, int, int]:
        """(queued json/pongs, pending states, pending frames) — for tests."""
        with self._cond:
            return (
                len(self._json_queue),
                int(self._state is not None),
                int(self._frame is not None),
            )

    def close(self, code: int = 1000, reason: str = "") -> None:
        with self._cond:
            if not self._alive:
                return
            self._alive = False
            self._cond.notify_all()
        # Outside `_cond`: `sendall` blocks on a phone that has stopped
        # reading, and holding the queue lock through it stalls the writer
        # thread that is being told to stop.
        try:
            with self._send_lock:
                self._sock.sendall(ws_codec.encode_close(code, reason))
        except OSError:
            pass
        try:
            self._sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass

    @property
    def alive(self) -> bool:
        return self._alive

    def _write_loop(self) -> None:
        while True:
            with self._cond:
                while (self._alive and not self._json_queue
                       and self._state is None and self._frame is None):
                    self._cond.wait(timeout=1.0)
                if not self._alive:
                    return
                if self._json_queue:
                    chunk = self._json_queue.popleft()
                elif self._state is not None:
                    state, self._state = self._state, None
                    chunk = ws_codec.encode_frame(
                        ws_codec.OP_TEXT,
                        json.dumps(state, separators=(",", ":")).encode("utf-8"),
                    )
                else:
                    chunk, self._frame = self._frame, None
            try:
                with self._send_lock:
                    self._sock.sendall(chunk)
            except OSError:
                with self._cond:
                    self._alive = False
                return
