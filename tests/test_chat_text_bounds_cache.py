# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""Streaming chat remeasures every segment. The bounds cache must stay large
enough, and a power of two, so the slot index stays a mask.
"""

import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PRIMITIVES = (
    ROOT
    / "src/source/blender/editors/space_mixie_chat/mixie_chat_ui_primitives.cc"
)


def test_chat_text_bounds_cache_has_room_for_a_long_transcript():
    source = PRIMITIVES.read_text(encoding="utf-8")
    match = re.search(r"#define TEXT_BOUNDS_CACHE_SLOTS\s+(\d+)", source)
    assert match, "TEXT_BOUNDS_CACHE_SLOTS must stay a named slot count"
    slots = int(match.group(1))
    assert slots == 4096
    assert slots & (slots - 1) == 0
    assert f"hash & (TEXT_BOUNDS_CACHE_SLOTS - 1)" in source
