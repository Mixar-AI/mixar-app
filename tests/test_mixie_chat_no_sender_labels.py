# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""The chat transcript draws no "You" / "Mixie" sender labels.

The bubble side already says who spoke, so ``mixie_chat_sender_label``
returns a label only for an error bubble or a user interjection that still
carries its delivery hint, and the renderer skips the draw on nullptr.
Source-level contract: the renderer is native C++.
"""

import re
from pathlib import Path

CHAT = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_mixie_chat"


def _sender_label_body() -> str:
    src = (CHAT / "mixie_chat_messages_content.cc").read_text()
    start = src.index("const char *mixie_chat_sender_label(")
    body = src[start:src.index("\n}\n", start)]
    return re.sub(r"/\*.*?\*/", "", body, flags=re.S)


def test_sender_label_never_returns_you_or_mixie():
    body = _sender_label_body()
    assert not re.search(r'"You\b', body)
    assert '"Mixie"' not in body
    assert 'return "Error";' in body
    assert "return nullptr;" in body
    assert "delivery_hint" in body


def test_renderer_skips_null_sender_label():
    src = (CHAT / "mixie_chat_messages_render.cc").read_text()
    assert "if (const char *label = mixie_chat_sender_label(layout, &msg_ptr))" in src
