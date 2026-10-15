# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Connection-scoped writer; large sends cannot block reads or tool replies."""
import threading
import time
from queue import Empty

from . import socket_liveness

# Idle writer ticks are 0.1 s apart; a longer gap means this thread was starved.
_STARVED_S = 1.0


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
                if client._connected and socket_liveness.tick(client, starved=starved):
                    return
                continue
            if stopped.is_set() or client._ws is not socket:
                return
            size = len(frame)
            client._diag.send_starting(size)
            try:
                socket.send(frame)
            except Exception as exc:
                # Was silent: a send that outlived the socket timeout (a large
                # frame on a slow uplink) tore the connection down unexplained.
                timeout = socket.gettimeout() if hasattr(socket, 'gettimeout') else None
                client._diag.end('writer_error', exc, send_bytes=size, socket_timeout_s=timeout,
                                 queued=client._outbound.qsize())
                client._connected = False
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
