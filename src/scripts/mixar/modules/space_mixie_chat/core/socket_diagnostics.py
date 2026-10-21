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

Besides the ending, each record says what the ending alone cannot:
``slept_s`` (the wall clock ran ahead of the monotonic one: the machine slept
under the socket), ``errno`` / ``winerror`` (Windows reports a reset receive
as a stale ``FileNotFoundError [Errno 2]``), and how far a frame in flight
had got. The handshake also says how THIS socket came to be (``reconnect``:
the attempt number, the backoff slept and the time since the previous socket
ended). An app that crashed or was killed while connected leaves a small
state file (``connection_state_<pid>.json``, refreshed every minute); the
next launch reports it as ``app_exited`` with the instance id it had.
"""

import atexit
import json
import os
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
# The wall clock ran this far ahead of the monotonic one: the machine slept.
_SLEPT_S = 5.0
# The state file of a live app is at most this old; an older one is a dead app's.
_ALIVE_EVERY_S = 60.0
_STALE_S = 3 * _ALIVE_EVERY_S
_STATE_PREFIX = 'connection_state_'


@dataclass
class SocketRecord:
    seq: int
    started_wall: float
    started: float
    attempt: int = 0          # failed sockets since the last good handshake
    waited_s: float = 0.0     # backoff slept before this socket's connect
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
    send_done: int = 0        # bytes of that frame already written
    send_started: float = 0.0
    max_loop_gap_s: float = 0.0
    reason: str = ''
    detail: dict = field(default_factory=dict)
    ended: float = 0.0
    ended_wall: float = 0.0


def _scrub(text):
    return _PATH.sub('<path>', str(text))[:_MESSAGE_CHARS]


def _state_dir():
    try:
        import bpy
        base = bpy.utils.user_resource('CONFIG', path='mixar', create=True)
    except Exception:  # noqa: BLE001 - outside Blender (tests) or no CONFIG dir
        return None
    return base if isinstance(base, str) and base else None


class SocketDiagnostics:
    """One per client. Thread-safe: the reader, the writer, the run loop and
    the UI may all end a socket; only the first reason is kept."""

    def __init__(self, instance_id='', state_dir=None):
        self._lock = threading.Lock()
        self._seq = 0
        self.current = None
        self._previous = None
        self._pending = deque(maxlen=MAX_PENDING)
        self._instance_id = str(instance_id or '')[:64]
        self._state_dir = state_dir if state_dir is not None else _state_dir()
        self._alive_at = 0.0
        if self._instance_id:  # the app's own agent client, not a test or a sandbox helper
            self._pending.extend(self._dead_apps())
            atexit.register(self.forget_state)

    def begin(self, attempt=0, waited_s=0.0):
        with self._lock:
            self._seq += 1
            self._previous, self.current = self.current, SocketRecord(
                self._seq, time.time(), time.monotonic(), attempt=attempt,
                waited_s=round(waited_s, 2))
            return self.current

    def reconnect(self):
        """How the current socket came to be, for its own handshake: the
        server learns the reconnect latency without trusting either clock."""
        record, previous = self.current, self._previous
        if record is None:
            return None
        info = {'attempt': record.attempt, 'waited_s': record.waited_s}
        if previous is not None and previous.ended:
            info.update(previous_seq=previous.seq, previous_reason=previous.reason,
                        after_s=round(time.monotonic() - previous.ended, 2))
        return info

    def phase(self, name):
        record = self.current
        if record is not None and not record.reason:
            record.phase = name
            if name == 'connected':
                record.connected_at = time.monotonic()
                self.alive(force=True)

    # Traffic: plain attribute writes, cheap enough for every frame.
    def send_starting(self, size):
        record = self.current
        if record is not None:
            record.sending, record.send_done, record.send_started = size, 0, time.monotonic()

    def send_progress(self, done):
        record = self.current
        if record is not None:
            record.send_done = done

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
            record.ended, record.ended_wall = time.monotonic(), time.time()
            if exc is not None:
                detail['exception'] = type(exc).__name__
                detail['message'] = _scrub(exc)
                for key in ('errno', 'winerror'):
                    code = getattr(exc, key, None)
                    if isinstance(code, int):
                        detail[key] = code
            if record.sending:
                # The writer was mid-frame: how big, how far, for how long.
                detail.setdefault('in_flight_send_bytes', record.sending)
                detail.setdefault('in_flight_sent_bytes', record.send_done)
                detail.setdefault('in_flight_send_s', round(record.ended - record.send_started, 2))
            slept = (record.ended_wall - record.started_wall) - (record.ended - record.started)
            if slept >= _SLEPT_S:
                detail.setdefault('slept_s', round(slept, 1))
            record.detail = {key: (_scrub(value) if isinstance(value, str) else value)
                             for key, value in detail.items()}
            report = self.report(record)
            self._pending.append(report)
        line = ' '.join(f'{key}={value}' for key, value in report.items() if key != 'reason')
        (logger.info if reason in _NORMAL else logger.warning)(
            f"[CONN] socket #{record.seq} ended: {reason} {line}")
        # The file exists only while a socket is connected: an app that sits
        # disconnected (offline) must never read as dead to a second Mixar.
        self.forget_state()

    @staticmethod
    def report(record):
        end = record.ended or time.monotonic()
        since = lambda t: round(end - t, 2) if t else None  # noqa: E731
        return {
            'socket_seq': record.seq,
            'reason': record.reason,
            'phase': record.phase,
            'started_at': round(record.started_wall, 3),
            'ended_at': round(record.ended_wall, 3) if record.ended_wall else None,
            'attempt': record.attempt,
            'waited_s': record.waited_s,
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
        sent = {id(report) for report in reports}
        with self._lock:
            kept = [report for report in self._pending if id(report) not in sent]
            self._pending.clear()
            self._pending.extend(kept)

    # --- an app that dies while connected -----------------------------------
    def _state_path(self, pid=None):
        if not self._state_dir:
            return None
        return os.path.join(self._state_dir, f'{_STATE_PREFIX}{pid or os.getpid()}.json')

    def alive(self, force=False, awaiting_result=None):
        """While connected, refresh this app's state file (writer tick; at most
        once a minute). ``awaiting_result`` is a callable, asked only when the
        file is written. Best effort: a read-only disk only loses the report."""
        record, now = self.current, time.time()
        path = self._state_path() if self._instance_id else None
        if (path is None or record is None or record.phase != 'connected' or record.reason
                or (not force and now - self._alive_at < _ALIVE_EVERY_S)):
            return
        self._alive_at = now
        state = {'instance_id': self._instance_id, 'socket_seq': record.seq,
                 'started_at': round(record.started_wall, 3), 'alive_at': round(now, 3)}
        if awaiting_result is not None:
            try:
                state['awaiting_result'] = bool(awaiting_result())
            except Exception:  # noqa: BLE001 - the flag is a hint, never a reason to skip
                pass
        try:
            with open(path, 'w', encoding='utf-8') as fh:
                json.dump(state, fh)
        except OSError as exc:
            logger.debug("Connection state not saved: %s", exc)

    def forget_state(self):
        """A clean stop or exit: nothing to report on the next launch."""
        path = self._state_path()
        if path:
            try:
                os.remove(path)
            except OSError:
                pass

    def _dead_apps(self):
        """State files of earlier app runs that never stopped cleanly."""
        if not self._state_dir:
            return []
        reports, now = [], time.time()
        try:
            names = [n for n in os.listdir(self._state_dir)
                     if n.startswith(_STATE_PREFIX) and n != f'{_STATE_PREFIX}{os.getpid()}.json']
        except OSError:
            return []
        for name in names[:MAX_PENDING]:
            path = os.path.join(self._state_dir, name)
            try:
                with open(path, encoding='utf-8') as fh:
                    state = json.load(fh)
                alive_at = float(state['alive_at'])
                if now - alive_at < _STALE_S:
                    continue  # another Mixar running beside this one
                os.remove(path)
            except (OSError, ValueError, KeyError, TypeError):
                continue
            report = {'socket_seq': int(state.get('socket_seq') or 0), 'reason': 'app_exited',
                      'phase': 'connected', 'started_at': state.get('started_at'),
                      'ended_at': round(alive_at, 3), 'down_s': round(now - alive_at, 1),
                      'instance_id': str(state.get('instance_id') or '')[:64]}
            if 'awaiting_result' in state:
                report['awaiting_result'] = bool(state['awaiting_result'])
            logger.warning(f"[CONN] previous app run ended while connected: {report}")
            reports.append(report)
        return reports
