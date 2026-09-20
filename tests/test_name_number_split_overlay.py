# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-2.0-or-later

"""The name-number splitter must never throw: a datablock named with a float
("Panel_Vert_0.6699999999999999", an agent-scripted coordinate) has a numeric
suffix wider than an int, and the uncaught `std::out_of_range` from
`std::stoi` aborted the app while the library-override resync populated the
name map on file load (big_city.mixar). The overlay parses with
`std::from_chars`, which reports overflow as an error code instead."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OVERLAY = ROOT / "src/source/blender/blenlib/intern/string_utils.cc"
UPSTREAM = ROOT / "upstream/source/blender/blenlib/intern/string_utils.cc"


def _strip_comments(text: str) -> str:
    return re.sub(r"/\*.*?\*/", "", text, flags=re.S)


def _split_fn(text: str) -> str:
    start = text.index("StringRef BLI_string_split_name_number(")
    return text[start : text.index("\n}\n", start)]


def test_the_overlay_parses_the_suffix_without_exceptions():
    text = OVERLAY.read_text(encoding="utf-8")
    fn = _strip_comments(_split_fn(text))
    assert "std::stoi" not in fn and "try {" not in fn
    assert "#include <charconv>" in text
    assert "std::from_chars(first, last, number)" in fn
    # Overflow (or trailing junk) means "no number": the whole string is the name.
    assert "parsed.ec == std::errc() && parsed.ptr == last" in fn
    assert "r_number = 0;" in fn


def test_the_overlay_only_differs_from_upstream_in_that_function_and_header():
    """Keep the overlay a one-hunk patch so an upstream bump is a re-copy."""
    if not UPSTREAM.exists():
        return
    up = UPSTREAM.read_text(encoding="utf-8")
    ov = OVERLAY.read_text(encoding="utf-8")
    up_rest = _strip_comments(up.replace(_split_fn(up), "")).replace("#include <charconv>\n", "")
    ov_rest = _strip_comments(ov.replace(_split_fn(ov), "")).replace("#include <charconv>\n", "")
    assert up_rest == ov_rest
