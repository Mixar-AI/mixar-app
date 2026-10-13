# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Preferences > Themes > Chat edits bTheme in place. The message layout
cache bakes each bubble's colours, font size and padding, and only rebuilt on
a new message, a width change or a stream — so theme edits never showed.
The cache now records a theme signature and rebuilds when it changes.
"""

from pathlib import Path


CHAT = Path(__file__).resolve().parents[1] / "src/source/blender/editors/space_mixie_chat"


def _read(name: str) -> str:
    return (CHAT / name).read_text(encoding="utf-8")


def _fn_body(src: str, signature: str) -> str:
    start = src.index(signature)
    open_brace = src.index("{", start)
    depth = 0
    for i in range(open_brace, len(src)):
        depth += {"{": 1, "}": -1}.get(src[i], 0)
        if depth == 0:
            return src[open_brace : i + 1]
    raise AssertionError(signature)


def test_signature_covers_the_chat_theme_block_and_scale():
    body = _fn_body(_read("mixie_chat_ui_theme.cc"), "uint64_t chat_ui_theme_signature()")
    assert "chat_ui_get_theme_space()" in body
    assert "mix(ts, sizeof(*ts));" in body
    assert "UI_SCALE_FAC" in body


def test_a_theme_change_rebuilds_the_layout_cache():
    draw = _read("mixie_chat_messages.cc")
    check = draw.index("chat_ui_theme_signature() != rt->prev_theme_signature")
    decision = draw[check : draw.index("if (needs_layout_rebuild) {", check)]
    assert "needs_layout_rebuild = true;" in decision


def test_the_rebuild_records_the_signature_it_used():
    build = _read("mixie_chat_messages_layout.cc")
    assert "rt->prev_theme_signature = chat_ui_theme_signature();" in build
    assert "uint64_t prev_theme_signature = 0;" in _read("mixie_chat_layout_data.hh")
