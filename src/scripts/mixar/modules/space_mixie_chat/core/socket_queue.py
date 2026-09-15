# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bound socket frames by both count and encoded bytes."""
from queue import Full, Queue


class SocketQueue(Queue):
    def __init__(self, maxsize=128, maxbytes=64 * 1024 * 1024):
        super().__init__(maxsize)
        self.maxbytes = maxbytes
        self.queued_bytes = 0

    def put_nowait(self, frame):
        size = len(frame.encode('utf-8'))
        with self.not_full:
            if self._qsize() >= self.maxsize or self.queued_bytes + size > self.maxbytes:
                raise Full
            self._put((frame, size))
            self.queued_bytes += size
            self.unfinished_tasks += 1
            self.not_empty.notify()

    def _get(self):
        frame, size = super()._get()
        self.queued_bytes -= size
        return frame
