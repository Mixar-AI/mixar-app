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
from ...constants import VOICE_FINAL_TIMEOUT_S, VOICE_SESSION_GRACE_S, VOICE_BUFFER_SECONDS
from .audio_buffer import AudioBuffer
from .token_lifetime import remaining, EXPIRY_MARGIN_S

logger = get_logger(__name__)


class Transport:
    def __init__(self, base_url, token, dictation_id):
        url = urlsplit(base_url)
        self.url = urlunsplit(('wss' if url.scheme == 'https' else 'ws', url.netloc,
                              '/api/v1/dictation/ws', '', ''))
        self.token, self.id = token, dictation_id
        self.base_url = base_url
        self.audio = AudioBuffer(VOICE_BUFFER_SECONDS)
        self.timings = {}
        self.began = time.monotonic()
        self.events = queue.Queue(maxsize=32)
        self.cancelled = threading.Event()
        self.stopping = threading.Event()
        self.thread = threading.Thread(target=self.run, daemon=True, name='mixar-dictation')

    def start(self):
        self.thread.start()

    def feed(self, data):
        self.audio.feed(data)

    def stop(self):
        self.stopping.set()

    def cancel(self):
        self.cancelled.set()
        self.audio.close()

    def emit(self, event):
        self.events.put_nowait(event)

    def _connect(self):
        refreshed = False
        lifetime = remaining(self.token)
        if lifetime is not None and lifetime <= EXPIRY_MARGIN_S and not self.cancelled.is_set():
            from mixar.modules.auth.core.auth import get_access_token, refresh_access_token
            current = get_access_token()
            if not current:
                raise ConnectionError('Authentication unavailable')
            if current == self.token:
                began_refresh = time.monotonic()
                result = refresh_access_token()
                refreshed = True
                self.timings['auth_refresh_ms'] = round((time.monotonic() - began_refresh) * 1000, 1)
                if not result.get('success'):
                    raise ConnectionError('Authentication refresh unavailable')
                current = get_access_token()
            if not current or self.cancelled.is_set():
                raise ConnectionError('Authentication unavailable')
            self.token = current
        try:
            return websocket.create_connection(self.url, timeout=10,
                                                header={'Authorization': 'Bearer ' + self.token})
        except websocket.WebSocketBadStatusException as exc:
            # FastAPI rejects unauthenticated WebSocket upgrades with HTTP 403.
            # Retry only that handshake (or 401), before Start or any audio.
            if exc.status_code not in (401, 403) or self.cancelled.is_set() or refreshed:
                raise
            from mixar.modules.auth.core.auth import get_access_token, refresh_access_token
            token = get_access_token()
            if not token:
                raise
            if token == self.token:
                began_refresh = time.monotonic()
                result = refresh_access_token()
                self.timings['auth_refresh_ms'] = round((time.monotonic() - began_refresh) * 1000, 1)
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
            from . import warmup
            began_connect = time.monotonic()
            ws = warmup.take(self.base_url, self.token)
            self.timings['warm_connection'] = ws is not None
            if ws is None:
                ws = self._connect()
            self.timings['backend_connect_ms'] = round((time.monotonic() - began_connect) * 1000, 1)
            self.token = ''
            if self.cancelled.is_set():
                return
            ws.settimeout(25)
            requested = time.monotonic()
            ws.send(json.dumps({'type': 'start', 'protocol_version': 1, 'dictation_id': self.id,
                                'buffered_audio_seconds': self.audio.bytes_pending / 32000}))
            ready = json.loads(ws.recv())
            if ready.get('type') != 'ready':
                self.emit({'type': 'error', 'message': ready.get('message', 'Voice input unavailable.')})
                return
            max_seconds = ready.get('max_duration_seconds')
            if type(max_seconds) is not int or not 1 <= max_seconds <= 600:
                raise ValueError('Invalid dictation recording limit')
            self.timings['start_to_ready_ms'] = round((time.monotonic() - requested) * 1000, 1)
            self.timings['click_to_ready_ms'] = round((time.monotonic() - self.began) * 1000, 1)
            self.timings['buffered_audio_ms'] = round(self.audio.bytes_pending / 32, 1)
            server = ready.get('timings_ms', {})
            if isinstance(server, dict):
                for key in ('auth', 'preparation_release', 'admission', 'provider_connect', 'provider_ready'):
                    value = server.get(key)
                    if type(value) in (int, float) and 0 <= value < 300000:
                        self.timings['server_' + key + '_ms'] = value
            logger.info('Dictation startup timings %s', self.timings)
            self.emit(ready)
            ws.settimeout(.02)
            began = time.monotonic()
            stopped_at = None
            sent_bytes = 0
            # Old relays allow only two seconds ahead of wall time. Pace their
            # catch-up instead of dropping buffered opening words.
            buffered_upload = ready.get('max_startup_buffer_seconds') == VOICE_BUFFER_SECONDS
            while time.monotonic() - began < max_seconds + VOICE_SESSION_GRACE_S:
                if self.cancelled.is_set():
                    ws.send('{"type":"cancel"}')
                    return
                # Drain only bounded queued audio, in order, before Stop.
                for _ in range(20):
                    if not buffered_upload and sent_bytes + 3200 > (time.monotonic() - began + 1.5) * 32000:
                        break
                    try:
                        data = self.audio.get_nowait()
                    except queue.Empty:
                        break
                    data = data[:max_seconds * 32000 - sent_bytes]
                    ws.settimeout(5)
                    ws.send_binary(data)
                    sent_bytes += len(data)
                    ws.settimeout(.02)
                    if sent_bytes == max_seconds * 32000:
                        self.audio.close()
                        self.stopping.set()
                        self.emit({'type': 'max_duration_reached', 'dictation_id': self.id})
                        break
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
                if event.get('type') == 'final' and stopped_at is not None:
                    self.timings['stop_to_final_ms'] = round((time.monotonic() - stopped_at) * 1000, 1)
                    logger.info('Dictation finish timings %s', self.timings)
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
            self.audio.close()
            if ws:
                ws.close(timeout=1)
