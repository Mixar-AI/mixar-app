# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Small additions to existing product events, never user-authored content."""

import time

from .capture import capture, _has_auth_token
from .constants import EVENT_MESSAGE_SENT, EVENT_UI_ACTION
from .preferences import is_enabled

_cinema_started = {}
_drawer_open_reported = False
_CINEMA_ENTER = frozenset({
    'mixar.director_enter', 'mixar.director_start',
    'mixar.director_new_shot', 'mixar.director_new_take',
})
_CINEMA_EXIT = frozenset({'mixar.director_finish', 'mixar.director_lock'})


def cinema_operator_properties(operator, result, context):
    """Add wall duration to the existing successful Cinema exit operator event.

    Each scene owns its clock. Re-entering an already open mode keeps its start;
    failed operations cannot start or finish a measurement. Unobserved entries
    have no duration, rather than an invented zero.
    """
    try:
        if operator not in _CINEMA_ENTER | _CINEMA_EXIT:
            return {}
        if not is_enabled() or not _has_auth_token():
            _cinema_started.clear()
            return {}
        if 'FINISHED' not in result:
            return {}
        scene = context.scene
        key = int(scene.session_uid)
        directing = bool(scene.mixar_director.is_directing)
        now = time.monotonic()
        if operator in _CINEMA_ENTER and directing:
            _cinema_started.setdefault(key, now)
        elif operator in _CINEMA_EXIT and not directing:
            started = _cinema_started.pop(key, None)
            if started is not None:
                return {'duration_seconds': round(max(0.0, now - started), 1)}
    except Exception:
        pass
    return {}


def reset_cinema_sessions():
    """A different document must never inherit an old scene's clock."""
    _cinema_started.clear()


def capture_scene_drawer_open(context):
    """One deliberate open per process, excluding reveals and opted-out clicks."""
    global _drawer_open_reported
    try:
        if _drawer_open_reported or not is_enabled() or not _has_auth_token():
            return
        from .journey_events import surface
        capture(EVENT_UI_ACTION, {
            'feature': 'scene_drawer', 'action': 'open',
            'outcome': 'finished', 'surface': surface(context),
        }, context=context)
        _drawer_open_reported = True
    except Exception:
        pass


def capture_agent_message(context, attachments, is_modify, is_awaiting_input,
                          mark_context=None):
    """Keep the existing send event; add only actual outgoing Scribble use."""
    scene = context.scene
    capture(EVENT_MESSAGE_SENT, {
        'mode': 'addon_project' if scene.mixie_chat_mode == 'ADDON_PROJECT' else 'agent',
        'has_attachments': bool(len(attachments)),
        'is_modify': is_modify, 'is_awaiting_input': is_awaiting_input,
        'plan_enabled': bool(getattr(scene, 'mixie_chat_plan_enabled', False)),
        'auto_mode': bool(getattr(scene, 'mixie_chat_auto_mode', False)),
        'model': getattr(scene, 'mixie_chat_model', '') or None,
        'has_scribble': bool(mark_context),
    }, context=context)


def capture_generate_message(context):
    """The legacy Generate-mode send remains unchanged."""
    scene = context.scene
    capture(EVENT_MESSAGE_SENT, {
        'mode': 'generate',
        'has_attachments': bool(len(scene.mixie_chat_pending_attachments)),
        'generate_type': getattr(scene, 'mixie_chat_generate_type', '') or None,
    }, context=context)
