# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Local dictation boundary: real coordinator, no microphone or network use."""
import queue

import aud
from mixar.modules.auth.core import auth
from mixar.modules.space_mixie_chat.core import voice
from mixar.modules.space_mixie_chat.core.voice_input import transport

saved = {}
latest = None


class LocalTransport:
    def __init__(self, *args):
        global latest
        # Background connection preparation also constructs a Transport; it
        # must not replace the recording whose final the scenario supplies.
        if not args or args[-1] != 'prepare':
            latest = self
        self.events = queue.Queue()
        self.timings = {}
        self.stopped = False

    def start(self):
        self.events.put({'type': 'ready', 'max_duration_seconds': 180})

    def feed(self, _):
        pass

    def stop(self):
        self.stopped = True

    def cancel(self):
        pass


def install():
    assert not saved
    voice.cancel()
    for name in ('_mixar_capture_permission', '_mixar_capture_open',
                 '_mixar_capture_read', '_mixar_capture_stop'):
        saved[(aud, name)] = getattr(aud, name)
    saved[(transport, 'Transport')] = transport.Transport
    saved[(auth, 'get_access_token')] = auth.get_access_token
    aud._mixar_capture_permission = lambda: 1
    aud._mixar_capture_open = object
    aud._mixar_capture_read = lambda _: b''
    aud._mixar_capture_stop = lambda _: b''
    transport.Transport = LocalTransport
    # Isolated offline profiles have no real login token. The transport is
    # replaced above; this synthetic token only satisfies its auth boundary.
    auth.get_access_token = lambda: 'qa-local-voice-placeholder'


def finish(text):
    assert latest.stopped, 'Stop must run through the real voice operator first'
    latest.events.put({'type': 'final', 'text': text})


def uninstall():
    voice.cancel()
    for (module, name), original in saved.items():
        setattr(module, name, original)
    saved.clear()
