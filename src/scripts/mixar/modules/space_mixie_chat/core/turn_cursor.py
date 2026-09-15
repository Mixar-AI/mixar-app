# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Keep the rendered cursor with the transcript when a project is saved."""

_KEY = 'mixie_ws_resume'


def read(scene, session_id, turn_id=None):
    if not hasattr(scene, 'get'):
        return {}
    saved = scene.get(_KEY)
    if saved is None or saved.get('session_id') != session_id:
        return {}
    if turn_id is not None and saved.get('turn_id') != turn_id:
        return {}
    return dict(saved)


def save(scene, turn):
    if not hasattr(scene, '__setitem__'):
        return
    scene[_KEY] = {
        'session_id': turn.session_id, 'turn_id': turn.turn_id,
        'cursor': turn.cursor, 'complete': turn.complete,
        'run_id': turn.run_id, 'run_open': bool(scene.mixie_run_open),
        'state': scene.mixie_chat_state,
    }
