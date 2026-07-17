# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""'@' mention autocomplete: ranking + replacement-text contract.

These pin the Python half of the mention bridge (mention_registry.py):
the C++ side (mixie_chat_mention.cc / interface_handlers.cc) splices
`insert_text` verbatim over the "@token" at the cursor, so the format and
the ranking order are frozen contracts, not cosmetic choices.
"""

import os
import sys
from unittest.mock import MagicMock

# src/scripts on sys.path + PEP 420 namespace packages mirror the runtime
# `mixar` package (bpy is stubbed by the root conftest).
_SRC_SCRIPTS = os.path.abspath(
    os.path.join(os.path.dirname(__file__), *([".."] * 4))
)
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

sys.modules.setdefault("bpy.app.handlers", MagicMock(name="bpy.app.handlers"))

from mixar.modules.space_mixie_chat.core.mention_registry import (  # noqa: E402
    Candidate,
    KIND_ASSET,
    KIND_MATERIAL,
    KIND_OBJECT,
    format_mention,
    rank_matches,
)
from mixar.modules.space_mixie_chat.constants import (  # noqa: E402
    MENTION_INSERT_MAXLEN,
    MENTION_MAX_ITEMS,
)


CANDIDATES = [
    Candidate("Sword", KIND_OBJECT),
    Candidate("Sword Handle", KIND_OBJECT),
    Candidate("rusty_sword", KIND_MATERIAL),
    Candidate("Shield", KIND_OBJECT),
    Candidate("Old Sword Asset", KIND_ASSET),
    Candidate("Stone", KIND_MATERIAL),
]


class TestFormatMention:
    def test_simple_name(self):
        assert format_mention("Sword") == "@Sword "

    def test_name_with_spaces_is_quoted(self):
        assert format_mention("Sword Handle") == '@"Sword Handle" '

    def test_trailing_space_always_present(self):
        # The trailing space ends the token — it is what closes the dropdown
        # after the C++ accept re-runs detection.
        for name in ("Cube", "My Cube", "Cube.001"):
            assert format_mention(name).endswith(" ")

    def test_oversized_name_rejected(self):
        assert format_mention("x" * (MENTION_INSERT_MAXLEN + 1)) == ""

    def test_fits_cpp_insert_buffer(self):
        # C++ reads insert_text into a 320-byte buffer and refuses anything
        # >= its size; the longest formatted mention must stay under that.
        longest = format_mention("x " * 140 + "x")  # spaces force quoting
        assert len(longest.encode("utf-8")) < 320

    def test_multibyte_names_measured_in_bytes(self):
        name = "å—" * (MENTION_INSERT_MAXLEN // 3)
        text = format_mention(name)
        assert text == "" or len(text.encode("utf-8")) <= MENTION_INSERT_MAXLEN


class TestRankMatches:
    def test_prefix_beats_substring(self):
        names = [m.name for m in rank_matches(CANDIDATES, "sw")]
        assert names.index("Sword") < names.index("rusty_sword")

    def test_word_boundary_beats_plain_substring(self):
        names = [m.name for m in rank_matches(CANDIDATES, "sword")]
        # "rusty_sword" matches at a word boundary ('_' split); it must rank
        # above nothing here but below the true prefixes.
        assert names[0] == "Sword"
        assert "Old Sword Asset" in names
        assert "rusty_sword" in names

    def test_case_insensitive(self):
        names = [m.name for m in rank_matches(CANDIDATES, "SWORD")]
        assert "Sword" in names

    def test_no_match_returns_empty(self):
        assert rank_matches(CANDIDATES, "zzz") == []

    def test_empty_query_lists_everything_capped(self):
        matches = rank_matches(CANDIDATES, "")
        assert len(matches) == min(len(CANDIDATES), MENTION_MAX_ITEMS)

    def test_limit_respected(self):
        assert len(rank_matches(CANDIDATES, "s", limit=2)) == 2

    def test_ties_break_shorter_then_alphabetical(self):
        names = [m.name for m in rank_matches(CANDIDATES, "sword")]
        assert names.index("Sword") < names.index("Sword Handle")

    def test_match_carries_kind_and_insert_text(self):
        match = next(m for m in rank_matches(CANDIDATES, "shield") if m.name == "Shield")
        assert match.kind == KIND_OBJECT
        assert match.insert_text == "@Shield "

    def test_spaced_name_insert_text_quoted(self):
        match = next(
            m for m in rank_matches(CANDIDATES, "sword") if m.name == "Sword Handle"
        )
        assert match.insert_text == '@"Sword Handle" '
