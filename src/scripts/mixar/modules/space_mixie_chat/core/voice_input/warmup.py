# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""One idle, authenticated backend socket. Never opens capture or Unmute."""
import json
import threading
import time

from mixar.config.logging_config import get_logger
from .token_lifetime import remaining, EXPIRY_MARGIN_S

logger = get_logger(__name__)
_candidate = None
_retry_at = 0.0
_identity = None


class WarmSocket:
    def __init__(self, base_url, token):
        self.key = (base_url, token)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.socket = None
        self.expires = 0.0
        self.timings = {}
        self.transferred = False
        self.thread = threading.Thread(target=self.run, daemon=True, name='mixar-voice-prepare')
        self.thread.start()

    def run(self):
        from .transport import Transport
        ws = None
        try:
            began = time.monotonic()
            opener = Transport(*self.key, 'prepare')
            ws = opener._connect()
            # _connect may rotate credentials. Bind lifetime and ownership to
            # the token that actually authenticated this socket.
            self.key = (self.key[0], opener.token)
            ws.settimeout(5)
            ws.send('{"type":"prepare","protocol_version":1}')
            prepared = json.loads(ws.recv())
            if prepared.get('type') != 'prepared':
                return  # Older/disabled backends stay on the on-demand path.
            ttl = prepared.get('expires_in_seconds')
            if type(ttl) is not int or not 1 <= ttl <= 300:
                return
            self.timings = {'prepare_ms': round((time.monotonic() - began) * 1000, 1)}
            lifetime = remaining(self.key[1])
            if lifetime is None or lifetime <= EXPIRY_MARGIN_S:
                return
            self.expires = time.monotonic() + min(ttl - 5, lifetime - EXPIRY_MARGIN_S)
            with self.lock:
                if self.stop.is_set():
                    return
                self.socket = ws
            logger.info('Dictation prepared backend_ms=%.1f', self.timings['prepare_ms'])
            while not self.stop.wait(15):
                with self.lock:
                    if self.socket is None or time.monotonic() >= self.expires:
                        break
                    ws.send('{"type":"ping"}')
                    if json.loads(ws.recv()).get('type') != 'pong':
                        break
        except Exception:
            # No raw transport exception: URLs/headers may contain credentials.
            logger.debug('Dictation preparation unavailable; on-demand connection remains available')
        finally:
            with self.lock:
                # A successful take owns the socket now; never close it here.
                transferred = self.transferred
                self.socket = None
                self.expires = 0
            if ws and not transferred:
                ws.close(timeout=1)

    def take(self):
        if not self.lock.acquire(timeout=.15):
            return None
        try:
            if self.socket is None or time.monotonic() >= self.expires:
                return None
            lifetime = remaining(self.key[1])
            if lifetime is None or lifetime <= EXPIRY_MARGIN_S:
                return None
            # Verify an idle socket before Start: reconnecting here cannot
            # replay audio or create a duplicate provider recording.
            try:
                self.socket.send('{"type":"ping"}')
                if json.loads(self.socket.recv()).get('type') != 'pong':
                    return None
            except Exception:
                return None
            lifetime = remaining(self.key[1])
            if lifetime is None or lifetime <= EXPIRY_MARGIN_S:
                return None
            ws, self.socket = self.socket, None
            self.transferred = True
            self.stop.set()
            return ws
        finally:
            self.lock.release()


def prepare(base_url, token):
    global _candidate, _retry_at, _identity
    key = (base_url, token)
    if key != _identity:
        shutdown()
        _identity, _retry_at = key, 0
    if _candidate and _candidate.thread.is_alive():
        return
    if time.monotonic() < _retry_at:
        return
    _candidate = WarmSocket(base_url, token)
    _retry_at = time.monotonic() + 60


def take(base_url, token):
    global _candidate, _retry_at
    candidate, _candidate = _candidate, None
    _retry_at = 0
    if candidate:
        ws = candidate.take() if candidate.key == (base_url, token) else None
        candidate.stop.set()
        return ws
    return None


def shutdown():
    global _candidate, _identity
    candidate, _candidate = _candidate, None
    _identity = None
    if candidate:
        candidate.stop.set()
