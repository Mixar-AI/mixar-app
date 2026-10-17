# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""Byte-aware composer bounds (space_mixie_chat/core/composer_limit.py)."""

from mixar.modules.space_mixie_chat import constants
from mixar.modules.space_mixie_chat.core import composer_limit


def test_capacity_is_maxlen_bytes():
    assert composer_limit.capacity_bytes(10) == 10
    assert composer_limit.capacity_bytes(constants.CHAT_INPUT_MAXLEN) == constants.CHAT_INPUT_MAXLEN


def test_fits_and_full_count_utf8_bytes():
    assert composer_limit.fits("abcde", 5)
    assert composer_limit.is_full("abcde", 5)
    assert not composer_limit.fits("abcdef", 5)
    assert not composer_limit.is_full("abcd", 5)
    assert not composer_limit.fits("éé", 3)  # 4 bytes, 3 fit
    assert composer_limit.fits("éé", 4)


def test_clamp_never_splits_a_character():
    kept, dropped = composer_limit.clamp("abc", 10)
    assert (kept, dropped) == ("abc", 0)
    kept, dropped = composer_limit.clamp("aééb", 4)  # bytes: a(1) é(2) é(2) b(1)
    assert kept == "aé" and dropped == 2
    kept, dropped = composer_limit.clamp("x" * 70000)
    assert len(kept) == constants.CHAT_INPUT_MAXLEN and dropped == 70000 - len(kept)


def test_composer_cap_is_generous_and_below_the_wire_limit():
    assert constants.CHAT_INPUT_MAXLEN >= 65536
    assert constants.CHAT_INPUT_MAXLEN + constants.CHAT_RULES_MAXLEN < constants.MAX_MESSAGE_LENGTH
