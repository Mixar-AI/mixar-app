# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later
"""How each agent socket ended, in the client's own words.

The server only sees a socket go quiet (``code=1006 silence=…``); the cause
lives here. Every socket of a client gets a sequence number; whichever path
ends it records the reason ONCE (first writer wins), with the exception, the
phase it died in and its traffic. Each record is logged locally as one
``[CONN]`` line and rides on the next handshake as ``connection_reports``, so
the backend logs it beside its own disconnect line (same connection id and
``socket_seq``). Nothing here may carry a local path, a token or a payload.
"""

import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field

from mixar.config.logging_config import get_logger

logger = get_logger(__name__)

MAX_PENDING = 20
_MESSAGE_CHARS = 300
_PATH = re.compile(r'(?:[A-Za-z]:\\|/(?:Users|home|private|var|tmp|Volumes)/)\S*')
# Ends the app chose; everything else is a fault worth a WARNING.
_NORMAL = {'client_stopped', 'consent_reconnect'}


@dataclass
class SocketRecord:
    seq: int
    started_wall: float
    started: float
    phase: str = 'connecting'
    connected_at: float = 0.0
    sent: int = 0
    sent_bytes: int = 0
    received: int = 0
    received_bytes: int = 0
    last_sent: float = 0.0
    last_received: float = 0.0
    largest_send: int = 0
    slowest_send_s: float = 0.0
    sending: int = 0          # size of the frame the writer is in, 0 when idle
    send_started: float = 0.0
    max_loop_gap_s: float = 0.0
    reason: str = ''
    detail: dict = field(default_factory=dict)
    ended: float = 0.0


def _scrub(text):
    return _PATH.sub('<path>', str(text))[:_MESSAGE_CHARS]


class SocketDiagnostics:
    """One per client. Thread-safe: the reader, the writer, the run loop and
    the UI may all end a socket; only the first reason is kept."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seq = 0
        self.current = None
        self._pending = deque(maxlen=MAX_PENDING)

    def begin(self):
        with self._lock:
            self._seq += 1
            self.current = SocketRecord(self._seq, time.time(), time.monotonic())
            return self.current

    def phase(self, name):
        record = self.current
        if record is not None and not record.reason:
            record.phase = name
            if name == 'connected':
                record.connected_at = time.monotonic()

    # Traffic: plain attribute writes, cheap enough for every frame.
    def send_starting(self, size):
        record = self.current
        if record is not None:
            record.sending, record.send_started = size, time.monotonic()

    def sent(self, size):
        record = self.current
        if record is None:
            return
        now = time.monotonic()
        took = now - record.send_started if record.sending else 0.0
        record.sent += 1
        record.sent_bytes += size
        record.last_sent = now
        record.largest_send = max(record.largest_send, size)
        record.slowest_send_s = max(record.slowest_send_s, took)
        record.sending = 0

    def received(self, size):
        record = self.current
        if record is not None:
            record.received += 1
            record.received_bytes += size
            record.last_received = time.monotonic()

    def loop_gap(self, seconds):
        """The reader loop went this long between iterations (a GIL-starved
        thread looks exactly like a dead network to the liveness check)."""
        record = self.current
        if record is not None and seconds > record.max_loop_gap_s:
            record.max_loop_gap_s = seconds

    def end(self, reason, exc=None, record=None, **detail):
        """Record why ``record`` (default: the current socket) ended. First wins."""
        with self._lock:
            record = record or self.current
            if record is None or record.reason:
                return
            record.reason = reason
            record.ended = time.monotonic()
            if exc is not None:
                detail['exception'] = type(exc).__name__
                detail['message'] = _scrub(exc)
            if record.sending:
                # The writer was mid-frame: how big, and for how long.
                detail.setdefault('in_flight_send_bytes', record.sending)
                detail.setdefault('in_flight_send_s', round(record.ended - record.send_started, 2))
            record.detail = {key: (_scrub(value) if isinstance(value, str) else value)
                             for key, value in detail.items()}
            report = self.report(record)
            self._pending.append(report)
        line = ' '.join(f'{key}={value}' for key, value in report.items() if key != 'reason')
        (logger.info if reason in _NORMAL else logger.warning)(
            f"[CONN] socket #{record.seq} ended: {reason} {line}")

    @staticmethod
    def report(record):
        end = record.ended or time.monotonic()
        since = lambda t: round(end - t, 2) if t else None  # noqa: E731
        return {
            'socket_seq': record.seq,
            'reason': record.reason,
            'phase': record.phase,
            'started_at': round(record.started_wall, 3),
            'lifetime_s': round(end - record.started, 2),
            'connected_s': since(record.connected_at),
            'sent': record.sent,
            'sent_bytes': record.sent_bytes,
            'received': record.received,
            'received_bytes': record.received_bytes,
            'since_last_send_s': since(record.last_sent),
            'since_last_receive_s': since(record.last_received),
            'largest_send_bytes': record.largest_send,
            'slowest_send_s': round(record.slowest_send_s, 2),
            'max_loop_gap_s': round(record.max_loop_gap_s, 2),
            **record.detail,
        }

    def pending_reports(self):
        with self._lock:
            return list(self._pending)

    def acknowledge(self, reports):
        """The server logged these; forget them (newer ones stay queued)."""
        sent = {report['socket_seq'] for report in reports}
        with self._lock:
            kept = [report for report in self._pending if report['socket_seq'] not in sent]
            self._pending.clear()
            self._pending.extend(kept)
