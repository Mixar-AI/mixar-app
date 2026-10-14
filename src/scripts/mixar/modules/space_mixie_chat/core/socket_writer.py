# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Connection-scoped writer; large sends cannot block reads or tool replies."""
import threading
from queue import Empty


def start_writer(client):
    socket = client._ws
    stopped = threading.Event()

    def write():
        while not stopped.is_set() and client._running.is_set() and client._ws is socket:
            try:
                frame = client._outbound.get(timeout=0.1)
            except Empty:
                client._expire_pending()
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
            client._expire_pending()

    thread = threading.Thread(target=write, name='MixarSocketWriter', daemon=True)
    thread.start()
    return stopped, thread
