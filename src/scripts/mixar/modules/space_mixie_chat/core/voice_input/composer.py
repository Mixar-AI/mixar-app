# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pure draft bookkeeping. Explicit send intent never survives an edit."""
from ...constants import CHAT_INPUT_MAXLEN


class Draft:
    def __init__(self, base, identity):
        self.base, self.identity = base, identity
        self.pending_send = False
        self.finished = False

    def final(self, text, current, identity):
        if self.finished or identity != self.identity:
            return None, False
        self.finished = True
        text = text.replace('\x1f', '').strip()
        if not text:
            return None, False
        # Preserve manual edits. Append the result, but require a new Send.
        send = self.pending_send and current == self.base
        sep = '' if not current or current[-1].isspace() else ' '
        value = current + sep + text
        if len(value) > CHAT_INPUT_MAXLEN:
            raise ValueError('Voice text exceeds the composer limit. Shorten the draft and try again.')
        return value, send
