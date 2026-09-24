# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Single-result mailbox for the native field that owns a dictation hold.

The native edit lifetime owns its token, caret, selection, limits and undo.
Python never stores a Button/RNA target pointer or writes a generation prompt.
"""


def begin(wm, token):
    wm.mixie_chat_voice_field_token = token
    wm.mixie_chat_voice_field_text = ''
    wm.mixie_chat_voice_field_ready = False


def clear(wm, token):
    if getattr(wm, 'mixie_chat_voice_field_token', '') != token:
        return
    wm.mixie_chat_voice_field_token = ''
    wm.mixie_chat_voice_field_text = ''
    wm.mixie_chat_voice_field_ready = False


def publish(wm, token, text):
    # Preserve paragraphs for multiline targets; native insertion flattens them
    # for single-line fields. Control bytes (including chat's submit marker)
    # must never become hidden field contents or commands.
    text = text.replace('\r\n', '\n').replace('\r', '\n').replace('\t', ' ')
    text = text.replace('\u2028', '\n').replace('\u2029', '\n')
    text = ''.join(c for c in text if c == '\n' or (ord(c) >= 32 and ord(c) != 127)).strip()
    begin(wm, token)
    wm.mixie_chat_voice_field_text = text
    wm.mixie_chat_voice_field_ready = True


def show_status(text):
    """Add a 3D viewport indicator alongside the native workspace status bar."""
    from mixar.modules.common.notifications import get_notification_store
    from ...constants import VOICE_TOAST_ID
    store = get_notification_store()
    key = VOICE_TOAST_ID + ':field-status'
    if not text:
        store.dismiss(key)
        return
    hint = 'Release Option/Alt to finish; Esc cancels.'
    if text == 'Finishing':
        hint = 'Keep this field open; Esc cancels.'
    store.push('info', text, hint, id=key, ttl_ms=0)
