# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""`.mixar` projects are FILE_TYPE_MIXAR, not FILE_TYPE_BLENDER, so every
file-browser preview gate that admits .blend files must admit them too."""

import re
from pathlib import Path


FILELIST = (
    Path(__file__).resolve().parents[1]
    / "src/source/blender/editors/space_file/filelist/filelist.cc"
)


def _function_body(source: str, signature: str) -> str:
    start = source.index(signature)
    return source[start : source.index("\n}\n", start)]


def test_mixar_files_are_polled_for_previews():
    body = _function_body(
        FILELIST.read_text(encoding="utf-8"),
        "static bool filelist_file_preview_load_poll(",
    )
    assert "FILE_TYPE_MIXAR" in body


def test_mixar_previews_read_the_embedded_blend_thumbnail():
    body = _function_body(
        FILELIST.read_text(encoding="utf-8"),
        "static void filelist_cache_preview_runf(",
    )
    branch = re.search(
        r"else if \(preview->flags & \(([^)]*)\)\)\s*\{\s*(?:/\*.*?\*/\s*)?"
        r"source = THB_SOURCE_BLEND;",
        body,
        re.S,
    )
    assert branch and "FILE_TYPE_MIXAR" in branch.group(1)


def test_mixar_files_get_the_blend_file_icon():
    source = FILELIST.read_text(encoding="utf-8")
    icon = _function_body(source, "static int filelist_geticon_file_type_ex(")
    assert "if (typeflag & FILE_TYPE_MIXAR) {\n    return ICON_FILE_BLEND;" in icon
    ext_icon = _function_body(source, "int ED_file_extension_icon(")
    assert "case FILE_TYPE_MIXAR:" in ext_icon
