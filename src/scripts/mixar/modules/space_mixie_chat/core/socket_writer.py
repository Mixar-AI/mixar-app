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
            try:
                socket.send(frame)
            except Exception:
                client._connected = False
                try:
                    socket.close()
                except Exception:
                    pass
                return
            client._expire_pending()

    thread = threading.Thread(target=write, name='MixarSocketWriter', daemon=True)
    thread.start()
    return stopped, thread
