# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-2.0-or-later
"""Pin the native footer's send visibility across agent and generation states."""

from pathlib import Path
import re

import pytest


@pytest.mark.parametrize('text,busy,generating,send', [
    (False, False, False, True), (True, False, False, True),
    (False, True, False, False), (True, True, False, True),
    (False, False, True, False), (True, False, True, False),
    (False, True, True, False), (True, True, True, False),
])
def test_generation_keeps_cancel_available(text, busy, generating, send):
    path = Path(__file__).resolve().parents[1] / 'src/source/blender/editors/space_mixie_chat/mixie_chat_footer.cc'
    expression = re.search(r'const bool show_send = (.*);', path.read_text()).group(1)
    expression = expression.replace('&&', ' and ').replace('||', ' or ').replace('!', ' not ')
    assert eval(expression.strip(), {'__builtins__': {}}, {
        'has_text': text, 'is_busy': busy, 'is_generating': generating,
    }) is send
