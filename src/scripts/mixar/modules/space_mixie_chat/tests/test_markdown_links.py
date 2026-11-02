# SPDX-FileCopyrightText: 2026 Adeveda Enterprises Private Limited
# SPDX-License-Identifier: GPL-3.0-or-later

"""A link's URL stays visible in the chat: the bubble cannot open links, so
``[text](url)`` renders as ``text (url)`` (a shared game's link was lost,
2026-10-23)."""

import os
import sys

_SRC_SCRIPTS = os.path.abspath(os.path.join(os.path.dirname(__file__), *([".."] * 4)))
if _SRC_SCRIPTS not in sys.path:
    sys.path.insert(0, _SRC_SCRIPTS)

from mixar.modules.space_mixie_chat.core.markdown_parser import parse_markdown_to_segments  # noqa: E402


def _texts(md):
    return [s.get("text") for s in parse_markdown_to_segments(md)]


def test_a_link_keeps_its_url_after_its_text():
    assert _texts("[**Play METRO DASH →**](https://play.mixar.app/api/play/QZ/)") == [
        "**Play METRO DASH →** (https://play.mixar.app/api/play/QZ/)"]


def test_a_link_that_shows_its_url_is_not_doubled():
    assert _texts("[https://a.b/c](https://a.b/c)") == ["https://a.b/c"]
    assert _texts("See <https://a.b/c> now") == ["See https://a.b/c now"]


def test_an_in_page_anchor_keeps_only_its_text():
    assert _texts("[top](#top)") == ["top"]


def test_a_link_in_a_list_item_keeps_its_url():
    segs = parse_markdown_to_segments("- [Docs](https://docs.example/x)")
    assert segs[0]["items"] == ["Docs (https://docs.example/x)"]
