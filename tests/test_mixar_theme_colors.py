# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""Shared Mixar UI colors are one theme palette across DNA, defaults, and XML."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DNA = (ROOT / "src/source/blender/makesdna/DNA_theme_types.h").read_text(encoding="utf-8")
CC = (ROOT / "src/source/blender/editors/interface/interface_mixar_theme.cc").read_text(encoding="utf-8")
USERDEF = (ROOT / "src/release/datafiles/userdef/userdef_default_theme.c").read_text(encoding="utf-8")
XML = (ROOT / "src/release/datafiles/userdef/Mixar_theme.xml").read_text(encoding="utf-8")

_ROW = re.compile(
    r"\{(false|true), offsetof\((ThemeUI|ThemeSpace), (\w+)\), \{(\d+), (\d+), (\d+), (\d+)\}\},"
)


def _slots():
    return list(_ROW.finditer(CC))


def test_slot_table_matches_dna_userdef_and_xml():
    rows = _slots()
    assert len(rows) >= 70
    for row in rows:
        agent, struct, name, r, g, b, a = row.groups()
        assert f"unsigned char {name}[4];" in DNA
        assert struct == ("ThemeSpace" if agent == "true" else "ThemeUI")
        hex8 = f"{int(r):02x}{int(g):02x}{int(b):02x}{int(a):02x}"
        assert f".{name} = RGBA(0x{hex8})," in USERDEF
        assert f'{name}="#{hex8}"' in XML


def test_shared_palette_defaults():
    text = CC
    assert "{false, offsetof(ThemeUI, mixar_canvas), {18, 18, 18, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_text), {226, 226, 226, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_focus), {0, 192, 199, 255}}," in text
    assert "{false, offsetof(ThemeUI, mixar_danger), {224, 72, 72, 255}}," in text
    assert "{true, offsetof(ThemeSpace, agent_border), {0, 255, 140, 255}}," in text


def test_space_mixie_and_chat_agree():
    assert ".space_mixie = {" in USERDEF
    chat = USERDEF.split(".space_mixie_chat = {", 1)[1].split("},", 1)[0]
    assert ".chat_mode_button_active = RGBA(0x00c0c7ff)," in chat
    assert ".chat_label_color = RGBA(0x757575ff)," in chat
    section = XML.split("<mixie_chat>", 1)[1].split("</mixie_chat>", 1)[0]
    assert 'chat_mode_button_active="#00c0c7ff"' in section
    for stale in ("#7e94d0", "#5a78c8", "#668cd9", "#70c62d"):
        assert stale not in section
        assert stale not in chat


def test_glass_wash_is_not_a_theme_slot():
    theme = (ROOT / "src/source/blender/editors/space_agent_bubble/agent_ui_theme.hh").read_text(
        encoding="utf-8"
    )
    assert "{0.075f, 0.078f, 0.075f, 0.40f}" in theme
    assert "{0.075f, 0.078f, 0.075f, 0.20f}" in theme
    assert "mixar_glass_wash" not in DNA
