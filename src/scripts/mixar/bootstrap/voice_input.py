# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Prepare dictation after login; never request permission or record at startup."""
import bpy

_permission_status = None


def _prepare():
    global _permission_status
    from mixar.modules.space_mixie_chat.core import voice
    from mixar.modules.space_mixie_chat.core.voice_input import warmup
    from mixar.modules.auth.core.auth import get_access_token
    from mixar.config.config import get_server_url
    if not voice.available():
        return None
    try:
        if _permission_status is None:
            import aud
            check = getattr(aud, '_mixar_capture_permission_status', None)
            _permission_status = check() if check else 0
        token = get_access_token()
        if not token:
            warmup.shutdown()
        elif not voice.is_listening():
            warmup.prepare(get_server_url(), token)
    except Exception:
        # Bootstrap is opportunistic. Voice still has a complete click path.
        pass
    return 5.0


def register():
    if not bpy.app.background and not bpy.app.timers.is_registered(_prepare):
        bpy.app.timers.register(_prepare, first_interval=3, persistent=True)


def unregister():
    from mixar.modules.space_mixie_chat.core.voice_input import warmup
    warmup.shutdown()
    if bpy.app.timers.is_registered(_prepare):
        bpy.app.timers.unregister(_prepare)
