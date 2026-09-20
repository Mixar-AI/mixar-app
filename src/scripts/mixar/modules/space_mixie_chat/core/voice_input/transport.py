# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Bounded audio streaming on a worker thread. This module never imports bpy."""
import json
import queue
import threading
import time
from urllib.parse import urlsplit, urlunsplit

import websocket

from mixar.config.logging_config import get_logger
from mixar.modules.common.network.core.errors import classify_network_error, log_network_failure
from ...constants import VOICE_FINAL_TIMEOUT_S, VOICE_SESSION_GRACE_S

logger = get_logger(__name__)


class Transport:
    def __init__(self, base_url, token, dictation_id):
        url = urlsplit(base_url)
        self.url = urlunsplit(('wss' if url.scheme == 'https' else 'ws', url.netloc,
                              '/api/v1/dictation/ws', '', ''))
        self.token, self.id = token, dictation_id
        self.audio = queue.Queue(maxsize=20)  # 2 seconds of 100 ms frames
        self.events = queue.Queue(maxsize=32)
        self.cancelled = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='mixar-dictation')

    def start(self):
        self.thread.start()

    def feed(self, data):
        for offset in range(0, len(data), 3200):
            self.audio.put_nowait(data[offset:offset + 3200])

    def stop(self):
        self.stopping.set()

    def cancel(self):
        self.cancelled.set()

    def emit(self, event):
        self.events.put_nowait(event)

    def _connect(self):
        try:
            return websocket.create_connection(self.url, timeout=10,
                                                header={'Authorization': 'Bearer ' + self.token})
        except websocket.WebSocketBadStatusException as exc:
            # FastAPI rejects unauthenticated WebSocket upgrades with HTTP 403.
            # Retry only that handshake (or 401), before Start or any audio.
            if exc.status_code not in (401, 403) or self.cancelled.is_set():
                raise
            from mixar.modules.auth.core.auth import get_access_token, refresh_access_token
            token = get_access_token()
            if not token:
                raise
            if token == self.token:
                result = refresh_access_token()
                if not result.get('success'):
                    raise
                token = get_access_token()
            if not token or self.cancelled.is_set():
                raise
            self.token = token
            # A rejection here propagates: no refresh loop or audio replay.
            return websocket.create_connection(self.url, timeout=10,
                                                header={'Authorization': 'Bearer ' + self.token})

    def run(self):
        ws = None
        try:
            ws = self._connect()
            self.token = ''
            if self.cancelled.is_set():
                return
            ws.send(json.dumps({'type': 'start', 'protocol_version': 1, 'dictation_id': self.id}))
            ready = json.loads(ws.recv())
            if ready.get('type') != 'ready':
                self.emit({'type': 'error', 'message': ready.get('message', 'Voice input unavailable.')})
                return
            max_seconds = ready.get('max_duration_seconds')
            if type(max_seconds) is not int or not 1 <= max_seconds <= 600:
                raise ValueError('Invalid dictation recording limit')
            self.emit(ready)
            ws.settimeout(.02)
            began = time.monotonic()
            stopped_at = None
            while time.monotonic() - began < max_seconds + VOICE_SESSION_GRACE_S:
                if self.cancelled.is_set():
                    ws.send('{"type":"cancel"}')
                    return
                # Drain only bounded queued audio, in order, before Stop.
                for _ in range(20):
                    try:
                        data = self.audio.get_nowait()
                    except queue.Empty:
                        break
                    ws.settimeout(5)
                    ws.send_binary(data)
                    ws.settimeout(.02)
                if self.stopping.is_set() and self.audio.empty() and stopped_at is None:
                    ws.send('{"type":"stop"}')
                    stopped_at = time.monotonic()
                if stopped_at is not None and time.monotonic() - stopped_at > VOICE_FINAL_TIMEOUT_S:
                    raise TimeoutError('Dictation finalization timed out')
                try:
                    raw = ws.recv()
                except websocket.WebSocketTimeoutException:
                    continue
                if not raw:
                    raise ConnectionError('Dictation closed before final text')
                if len(raw) > 65536:
                    raise ValueError('Invalid dictation response')
                event = json.loads(raw)
                if event.get('dictation_id') != self.id:
                    raise ValueError('Unexpected dictation session')
                self.emit(event)
                if event.get('type') in ('final', 'error', 'cancelled'):
                    return
            raise TimeoutError('Dictation timed out')
        except Exception as exc:
            if not self.cancelled.is_set():
                failure = classify_network_error(exc, self.url)
                log_network_failure(logger, failure, 'dictation')
                try:
                    self.emit({'type': 'error', 'message': f'Voice connection failed ({failure.support_code}). Please try again.'})
                except queue.Full:
                    pass
        finally:
            self.token = ''
            if ws:
                ws.close(timeout=1)
