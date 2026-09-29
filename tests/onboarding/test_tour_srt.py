# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
#
# SPDX-License-Identifier: GPL-3.0-or-later

"""SubRip parsing, cue lookup and wrapping for the tour's subtitle band."""

import sys
from unittest.mock import MagicMock

if "requests" not in sys.modules:
    sys.modules["requests"] = MagicMock(name="requests")

from mixar.modules.onboarding.core.tour import srt  # noqa: E402

SAMPLE = "﻿1\r\n00:00:01,500 --> 00:00:03,400\r\nSalut, je suis Namit.\r\n\r\n" \
         "2\r\n00:00:03,780 --> 00:00:07,130\r\nDans les prochaines minutes,\r\n" \
         "je vais vous faire visiter.\r\n\r\n\r\n" \
         "00:01:02.000 --> 00:01:03.000\r\nSans index, point décimal.\r\n\r\n" \
         "4\r\n00:00:09,000 --> 00:00:08,000\r\nfin avant début, ignoré\r\n\r\n" \
         "5\r\nbroken timing line\r\ntexte\r\n"


def test_parse_is_forgiving_and_sorted():
    subs = srt.parse(SAMPLE, "fr")
    assert subs.code == "fr"
    assert [c.start_ms for c in subs.cues] == [1500, 3780, 62000]
    assert subs.cues[0].end_ms == 3400
    assert subs.cues[1].text == "Dans les prochaines minutes,\nje vais vous faire visiter."
    assert subs.cues[2].text == "Sans index, point décimal."


def test_cue_at_is_half_open_and_empty_in_gaps():
    subs = srt.parse(SAMPLE)
    assert subs.text_at(1499) == ""
    assert subs.text_at(1500).startswith("Salut")
    assert subs.text_at(3399).startswith("Salut")
    assert subs.text_at(3400) == ""            # gap before the next cue
    assert subs.text_at(3780).startswith("Dans")
    assert subs.text_at(200000) == ""


def test_empty_input_has_no_cues():
    assert srt.parse("").cues == ()
    assert srt.parse("garbage\n\nmore").cues == ()


def _measure(text):
    return 10.0 * len(text)


def test_wrap_breaks_on_spaces_and_keeps_explicit_lines():
    lines = srt.wrap("one two three four\nfive", 70.0, _measure)
    assert lines == ["one two", "three", "four", "five"]


def test_wrap_splits_spaceless_scripts_per_character():
    lines = srt.wrap("这是一个很长的句子", 40.0, _measure)
    assert lines == ["这是一个", "很长的句", "子"]


def test_wrap_never_returns_nothing():
    assert srt.wrap("", 100.0, _measure) == [""]


def test_load_missing_file_is_none(tmp_path, monkeypatch):
    monkeypatch.setattr(srt.config, "assets_dir", lambda: str(tmp_path))
    assert srt.load("fr") is None
    (tmp_path / "tour" / "subtitles").mkdir(parents=True)
    (tmp_path / "tour" / "subtitles" / "fr.srt").write_text(SAMPLE, encoding="utf-8")
    subs = srt.load("fr")
    assert subs is not None and len(subs.cues) == 3
    (tmp_path / "tour" / "subtitles" / "de.srt").write_text("", encoding="utf-8")
    assert srt.load("de") is None
