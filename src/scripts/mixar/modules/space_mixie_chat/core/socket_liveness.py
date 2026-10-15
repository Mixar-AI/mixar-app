# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Dead-path detection, shared by the reader and the writer thread.

A path that dies under an open socket shows only as inbound silence: sends
keep "succeeding" into the kernel buffer (prod 2026-10-15: a chat frame
vanished, the socket stayed connected for 70 s). Two triggers start a probe
ping:

* WS_LIVENESS_TIMEOUT of silence — the idle watchdog;
* WS_ACK_TIMEOUT of silence while the client waits on the server: a command
  sent with no answer (the server answers within ~100 ms), or a turn whose
  result is still due — the path is suspect long before the idle watchdog
  would notice.

Neither fast trigger fires while our last frames may still be uploading: at
WS_ACK_MIN_UPLINK_BPS (uploaded(), since a local proxy or antivirus can hide
the upload from the kernel), or while a large kernel send backlog keeps
draining (progress()).

A reply to the probe (or to anything else we sent) within
WS_LIVENESS_PROBE_GRACE proves the link alive; a server ping or stream event
does not, since it proves only the downstream. None means dead: the socket
is aborted without a close handshake (nothing on a dead path would answer
one), the reader wakes at once and the run loop reconnects, where turn_events
resends a command the server never saw.

The writer ticks every 0.1 s, so it judges on time; the reader may sit 10 s
in one read. A thread that was itself starved (Blender's main thread holding
the GIL through a long script) restarts the grace instead of judging: its own
silence proves nothing.
"""
import socket
import struct
import sys
import time

from mixar.config.logging_config import get_logger

from ..constants import (
    WS_ACK_MIN_UPLINK_BPS,
    WS_ACK_TIMEOUT,
    WS_LIVENESS_PROBE_GRACE,
    WS_LIVENESS_TIMEOUT,
)

logger = get_logger(__name__)

_SO_NWRITE = 0x1024  # macOS: bytes in the send buffer, unsent or not yet acknowledged
# A backlog this large draining is an upload under way. Smaller ones prove
# nothing: the first hop (a proxy, Cloudflare's edge) acks a keepalive ping
# whether or not the server behind it is reachable (D5 2026-10-15).
_UPLOAD_BACKLOG = 16 * 1024
# The backlog shrank this recently: the upload is still moving.
_UPLOADING_S = 1.0


def send_backlog(ws):
    """Bytes the kernel still holds for the peer (unsent + unacknowledged), or
    None where the platform cannot say (Windows)."""
    sock = getattr(ws, 'sock', None)
    if sock is None:
        return None
    try:
        if sys.platform == 'darwin':
            return sock.getsockopt(socket.SOL_SOCKET, _SO_NWRITE)
        if sys.platform.startswith('linux'):
            import fcntl
            import termios
            return struct.unpack('i', fcntl.ioctl(sock.fileno(), termios.TIOCOUTQ, b'\0' * 4))[0]
    except Exception:  # noqa: BLE001 — a closed or foreign socket: no evidence either way
        return None
    return None


def await_ack(client, request_id):
    """Watch ``request_id`` for an answer once its frame has left the client."""
    with client._pending_lock:
        client._awaiting_ack[request_id] = None


def uploaded(client, size):
    """Writer, after each send: the bytes may still be crossing a slow uplink
    until this clock clears. Often invisible to the kernel backlog — a local
    proxy or TLS-inspecting antivirus swallows a frame at once and uploads it
    at the link's pace (C1 2026-10-15: a live 16 KB/s upload torn down) — so
    nothing counts as unanswered before then."""
    now = time.time()
    client._upload_clear_at = max(client._upload_clear_at, now) + size / WS_ACK_MIN_UPLINK_BPS


def progress(client):
    """Writer, every idle tick: a large kernel send backlog that keeps shrinking
    is an upload still moving on a slow uplink. It holds the fast probes off; it
    never counts as an answer (only the server's reply proves the path)."""
    backlog = send_backlog(client._ws)
    if backlog is None:
        client._send_backlog = None
        return
    previous = client._send_backlog
    if previous is not None and previous >= _UPLOAD_BACKLOG and backlog < previous:
        client._last_send_progress = time.time()
    client._send_backlog = backlog


def drained(client):
    """Writer: the outbound queue is empty, so every watched frame has left."""
    if not client._awaiting_ack:
        return
    now = time.time()
    with client._pending_lock:
        for request_id in list(client._awaiting_ack):
            if request_id not in client._pending_callbacks:
                client._awaiting_ack.pop(request_id)  # answered, expired or failed
            elif client._awaiting_ack[request_id] is None:
                client._awaiting_ack[request_id] = now


def _heard(client):
    """Last sign of life: any inbound frame, or an upload still moving."""
    return max(client._last_recv_time, client._last_send_progress)


def _answered(client):
    """Last proof the UPSTREAM works: the server replied to something we sent.
    A server ping or event proves only the downstream — a path dead one way
    kept its socket "alive" for 100 s in prod."""
    return client._last_reply_time


def _uploading(client, now):
    return now - client._last_send_progress <= _UPLOADING_S


def _awaiting_result():
    try:
        from .turn_events import awaiting_results
        return awaiting_results()
    except Exception:  # noqa: BLE001
        return False


def _trigger(client, now):
    silent = now - _heard(client)
    if silent > WS_LIVENESS_TIMEOUT:
        return 'silence'
    # Our last frames may still be uploading: by the slow-uplink clock
    # (uploaded()), or a large kernel backlog still draining (progress()).
    busy_until = max(client._upload_clear_at, client._last_send_progress)
    if now - busy_until <= WS_ACK_TIMEOUT:
        return None
    with client._pending_lock:
        sent = [t for rid, t in client._awaiting_ack.items()
                if t is not None and rid in client._pending_callbacks]
    if sent and now - min(sent) > WS_ACK_TIMEOUT and now - _answered(client) > WS_ACK_TIMEOUT:
        return 'unanswered'
    # Accepted, then the path died before the result (2026-10-15 run, D3):
    # a turn whose result is still due counts as waiting on the server too.
    if silent > WS_ACK_TIMEOUT and _awaiting_result():
        return 'unanswered'
    return None


def _probe_not_sent(client):
    record = getattr(client._diag, 'current', None)
    return client._outbound.qsize() > 0 or bool(record is not None and record.sending)


def tick(client, starved=False):
    """Start, keep or judge the probe. True once the socket was declared dead."""
    now = time.time()
    with client._liveness_lock:
        started = client._liveness_probe_started
        if started is not None and _answered(client) >= started:
            client._liveness_probe_started = started = None  # the probe was answered
        if started is None:
            why = _trigger(client, now)
            if why is None:
                return False
            client._liveness_probe_started = now
            client._liveness_probe_why = why
            logger.info(f"No WebSocket traffic for {now - _heard(client):.0f}s, no reply for "
                        f"{now - _answered(client):.0f}s"
                        f"{' while waiting on the server' if why == 'unanswered' else ''}"
                        f" — probing liveness before teardown")
            client._send_ping()
            return False
        if starved or _probe_not_sent(client) or _uploading(client, now):
            # Our own silence proves nothing: this thread slept, or the probe
            # still waits behind a frame being written or draining (a slow,
            # live upload).
            client._liveness_probe_started = now
            return False
        if now - started <= WS_LIVENESS_PROBE_GRACE:
            return False
        client._liveness_probe_started = None
        why = client._liveness_probe_why
    silent_s = round(now - _heard(client), 1)
    unanswered_s = round(now - _answered(client), 1)
    logger.warning(f"No reply for {unanswered_s:.0f}s (no traffic at all for {silent_s:.0f}s) and "
                   f"the liveness probe got no answer in {WS_LIVENESS_PROBE_GRACE:.0f}s — "
                   f"treating connection as dead")
    client._diag.end('liveness_timeout' if why == 'silence' else 'ack_timeout', silent_s=silent_s,
                     unanswered_s=unanswered_s, send_backlog=client._send_backlog)
    client._connected = False
    abort(client._ws)
    return True


def abort(ws):
    """Drop the socket now, waking a reader blocked in recv (a bare close does not)."""
    sock = getattr(ws, 'sock', None)
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except Exception:
            pass
    try:
        ws.shutdown()
    except Exception:
        pass
