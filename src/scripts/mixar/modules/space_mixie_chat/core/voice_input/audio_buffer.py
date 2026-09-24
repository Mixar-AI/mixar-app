# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Byte-bounded, ordered PCM queue shared by capture and network threads."""
from collections import deque
import queue
import threading


class AudioBuffer:
    def __init__(self, seconds):
        self.limit = seconds * 32000
        self.frames = deque()
        self.size = 0
        self.closed = False
        self.lock = threading.Lock()

    def feed(self, data):
        with self.lock:
            if self.closed:
                return
            if self.size + len(data) > self.limit:
                raise queue.Full
            self.frames.extend(data[i:i + 3200] for i in range(0, len(data), 3200))
            self.size += len(data)

    @property
    def bytes_pending(self):
        with self.lock:
            return self.size

    def get_nowait(self):
        with self.lock:
            if not self.frames:
                raise queue.Empty
            frame = self.frames.popleft()
            self.size -= len(frame)
            return frame

    def empty(self):
        return self.bytes_pending == 0

    def clear(self):
        with self.lock:
            self.frames.clear()
            self.size = 0

    def close(self):
        """Discard surplus and reject late capture feeds atomically."""
        with self.lock:
            self.closed = True
            self.frames.clear()
            self.size = 0
