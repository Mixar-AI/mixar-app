# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Connection-scoped writer; large sends cannot block reads or tool replies."""
import threading
import time
from queue import Empty

from . import socket_liveness

# Idle writer ticks are 0.1 s apart; a longer gap means this thread was starved.
_STARVED_S = 1.0
# One TLS write of a whole frame must finish inside the 10 s socket timeout, so
# a 1 MB render result on a ~100 KB/s uplink could never leave (prod
# 2026-10-18..20: 181 sockets cut at exactly 10.0 s, median frame 1.1 MB, one
# desktop 11 sockets in a row). Written in slices, each slice gets its own
# timeout: only an upload that stops moving fails.
_SLICE = 64 * 1024


def _send(client, socket, frame):
    if len(frame) <= _SLICE:
        socket.send(frame)
        return
    from websocket import ABNF, WebSocketTimeoutException

    message = ABNF.create_frame(frame, ABNF.OPCODE_TEXT)
    if getattr(socket, 'get_mask_key', None):
        message.get_mask_key = socket.get_mask_key
    data = message.format()
    done = 0
    with socket.lock:  # a ping or close never lands inside this frame
        while done < len(data):
            written = socket._send(data[done:done + _SLICE])
            if not written:  # the wait for a writable socket timed out
                raise WebSocketTimeoutException('The write operation timed out')
            done += written
            client._diag.send_progress(done)
            client._last_send_progress = time.time()  # still moving: hold the probes off


def start_writer(client):
    socket = client._ws
    stopped = threading.Event()

    def write():
        last = time.monotonic()
        while not stopped.is_set() and client._running.is_set() and client._ws is socket:
            try:
                frame = client._outbound.get(timeout=0.1)
            except Empty:
                client._expire_pending()
                now = time.monotonic()
                starved, last = now - last > _STARVED_S, now
                # Queue empty: every watched command has left; judge the path on time.
                socket_liveness.progress(client)
                socket_liveness.drained(client)
                client._diag.alive(awaiting_result=socket_liveness._awaiting_result)
                if client._connected and socket_liveness.tick(client, starved=starved):
                    return
                continue
            if stopped.is_set() or client._ws is not socket:
                return
            size = len(frame)
            client._diag.send_starting(size)
            try:
                _send(client, socket, frame)
            except Exception as exc:
                # Was silent: a send that outlived the socket timeout (a large
                # frame on a slow uplink) tore the connection down unexplained.
                timeout = socket.gettimeout() if hasattr(socket, 'gettimeout') else None
                client._diag.end('writer_error', exc, send_bytes=size, socket_timeout_s=timeout,
                                 queued=client._outbound.qsize())
                client._connected = False
                # Wake the reader blocked in its 10 s read: a bare close did
                # not, so every writer failure reconnected ~10 s late
                # (disconnect matrix 2026-10-20: reconnect_after_s=9.7).
                socket_liveness.abort(socket)
                try:
                    socket.close()
                except Exception:
                    pass
                return
            client._diag.sent(size)
            socket_liveness.uploaded(client, size)
            client._expire_pending()
            last = time.monotonic()

    thread = threading.Thread(target=write, name='MixarSocketWriter', daemon=True)
    thread.start()
    return stopped, thread
